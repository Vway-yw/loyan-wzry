"""王者荣耀热点插件 — 热点列表 + 输序号查看正文详情"""
import asyncio
import html as html_lib
import re
import time
import urllib.parse
import urllib.request
import http.cookiejar
from typing import Dict, List, Optional

from loyan.core.decorators import on_command, plugin_handler, PluginContext
from graci import get_logger

logger = get_logger("WZRY热点")

SEARCH_URL = "https://weixin.sogou.com/weixin?type=2&query={query}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 15
MAX_ITEMS = 10
LIST_TTL = 1800   # 列表缓存 30 分钟
DETAIL_TTL = 600  # 正文缓存 10 分钟

_cache: Dict[str, tuple] = {}
_detail_cache: Dict[str, tuple] = {}

# 每个命令主题 -> (回复头, 搜索关键词)
TOPICS = {
    "hot": ("🔥 王者荣耀热点", "王者荣耀"),
    "leak": ("⚡ 王者荣耀最新爆料", "王者荣耀 爆料 更新 皮肤"),
    "guide": ("📖 王者荣耀攻略", "王者荣耀 攻略"),
}


def _strip(tag_text: str) -> str:
    t = re.sub(r"<[^>]+>", "", tag_text)
    return html_lib.unescape(t).strip()


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://weixin.sogou.com/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_list(html: str, limit: int = MAX_ITEMS) -> List[Dict]:
    """解析搜索结果：标题 + 跳转链接"""
    items = []
    for m in re.finditer(r'<div class="txt-box">(.*?)</li>', html, re.S):
        seg = m.group(1)
        title_m = re.search(r'<a[^>]*uigs="article_title_\d+"[^>]*>(.*?)</a>', seg, re.S)
        href_m = re.search(r'<a[^>]*href="(/link\?url=[^"]+)"', seg)
        acct_m = re.search(r'class="all-time-y2">([^<]+)</span>', seg)
        ts_m = re.search(r"timeConvert\('(\d+)'\)", seg)
        if not title_m:
            continue
        item = {
            "title": _strip(title_m.group(1)),
            "href": href_m.group(1) if href_m else "",
            "account": acct_m.group(1).strip() if acct_m else "",
            "time": time.strftime("%m-%d %H:%M", time.localtime(int(ts_m.group(1)))) if ts_m else "",
        }
        if item["title"]:
            items.append(item)
        if len(items) >= limit:
            break
    return items


async def _get_list(query: str) -> Optional[List[Dict]]:
    """带缓存获取列表"""
    now = time.time()
    cached = _cache.get(query)
    if cached and now - cached[0] < LIST_TTL:
        return cached[1]
    html = await asyncio.to_thread(_fetch, SEARCH_URL.format(query=urllib.parse.quote(query)))
    items = _parse_list(html)
    if items:
        _cache[query] = (now, items)
    return items or None


async def _get_detail(href: str) -> Optional[str]:
    """跟随搜狗跳转抓取公众号正文（带缓存）"""
    if not href:
        return None
    now = time.time()
    cached = _detail_cache.get(href)
    if cached and now - cached[0] < DETAIL_TTL:
        return cached[1]
    try:
        text = await asyncio.to_thread(_fetch_detail, href)
        if text:
            _detail_cache[href] = (now, text)
        return text
    except Exception as e:
        logger.error(f"抓取正文失败: {e}")
        return None


def _fetch_detail(href: str) -> Optional[str]:
    """同步抓正文：跟随中间页 JS 拼接出 mp.weixin.qq.com 地址"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    link = "https://weixin.sogou.com" + href.replace("&amp;", "&")
    r = opener.open(urllib.request.Request(link, headers={"User-Agent": UA}), timeout=TIMEOUT)
    mid = r.read().decode("utf-8", errors="replace")
    parts = re.findall(r"url\s*\+?=\s*'([^']*)'", mid)
    final = "".join(parts)
    if not final.startswith("http"):
        return None
    r2 = opener.open(urllib.request.Request(final, headers={"User-Agent": UA}), timeout=TIMEOUT)
    body = r2.read().decode("utf-8", errors="replace")
    content = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', body, re.S)
    if not content:
        return None
    text = re.sub(r"<[^>]+>", "", content.group(1))
    text = html_lib.unescape(text).strip()
    # 去掉大量空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or None


def _pick_page(ctx, maxn: int) -> Optional[tuple]:
    """解析 序号 [页码]：返回 (序号, 页码)"""
    rest = (ctx.raw_text or "").strip()
    parts = rest.split(None, 2)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return None
    idx = int(parts[1].strip())
    if not (1 <= idx <= maxn):
        return None
    page = 1
    if len(parts) > 2 and parts[2].strip().isdigit():
        page = max(1, int(parts[2].strip()))
    return (idx, page)


PAGE_SIZE = 800


async def _handle_topic(ctx: PluginContext, topic: str, extra: str = ""):
    title, query = TOPICS[topic]
    if extra:
        query += " " + extra
    items = await _get_list(query)
    if not items:
        await ctx.reply("😢 暂时没有获取到内容，请稍后再试")
        return
    pick = _pick_page(ctx, len(items))
    if pick:
        idx, page = pick
        it = items[idx - 1]
        text = await _get_detail(it["href"])
        lines = [f"📄 {it['title']}", "━━━━━━━━━━━━"]
        if text:
            total = max(1, (len(text) + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(page, total)
            start = (page - 1) * PAGE_SIZE
            lines.append(text[start:start + PAGE_SIZE])
            lines.append("━━━━━━━━━━━━")
            lines.append(f"📄 第 {page}/{total} 页 · 📌 {' | '.join(x for x in (it.get('account'), it.get('time')) if x)}")
            if page < total:
                lines.append(f"💡 继续看：{ctx.command} {idx} {page + 1}")
        else:
            lines.append("（正文获取失败）")
        await ctx.reply("\n".join(lines))
        return
    lines = [title, "━━━━━━━━━━━━"]
    for i, it in enumerate(items, 1):
        t = it['title'] if len(it['title']) <= 30 else it['title'][:30] + '…'
        lines.append(f"{i}. {t}")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"💡 回复 {ctx.command} 序号（如 1）查看正文")
    await ctx.reply("\n".join(lines))


@on_command("/王者热点", "/王者荣耀热点", "/王者资讯")
@plugin_handler
async def handle_wzry(ctx: PluginContext):
    """查看王者荣耀热点（输序号看正文）"""
    await ctx.reply("🔥 正在获取王者荣耀热点...")
    try:
        await _handle_topic(ctx, "hot")
    except Exception as e:
        logger.error(f"王者热点失败: {e}")
        await ctx.reply("❌ 获取失败，请稍后再试")


@on_command("/王者爆料", "/王者荣耀爆料", "/王者更新")
@plugin_handler
async def handle_wzry_leak(ctx: PluginContext):
    """查看王者荣耀爆料（输序号看正文）"""
    await ctx.reply("⚡ 正在获取王者荣耀爆料...")
    try:
        await _handle_topic(ctx, "leak")
    except Exception as e:
        logger.error(f"王者爆料失败: {e}")
        await ctx.reply("❌ 获取失败，请稍后再试")


@on_command("/王者攻略", "/王者荣耀攻略")
@plugin_handler
async def handle_wzry_guide(ctx: PluginContext):
    """查看王者荣耀攻略（输序号看正文；/王者攻略 <英雄名> 定向）"""
    rest = (ctx.raw_text or "").strip()
    parts = rest.split(None, 1)
    hero = parts[1].strip() if len(parts) > 1 else ""
    await ctx.reply("📖 正在获取王者荣耀攻略...")
    try:
        await _handle_topic(ctx, "guide", hero)
    except Exception as e:
        logger.error(f"王者攻略失败: {e}")
        await ctx.reply("❌ 获取失败，请稍后再试")
