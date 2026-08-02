"""王者荣耀热点插件 — 从搜狗微信搜索抓取王者荣耀公众号热点/爆料/攻略资讯"""
import asyncio
import html as html_lib
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from loyan.core.decorators import on_command, plugin_handler, PluginContext
from graci import get_logger

logger = get_logger("WZRY热点")

SEARCH_URL = "https://weixin.sogou.com/weixin?type=2&query={query}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 15
MAX_ITEMS = 10
CACHE_TTL = 1800  # 30 分钟缓存，保证时效性

_cache: Dict[str, tuple] = {}  # key -> (timestamp, titles)


def _fetch(query: str) -> str:
    url = SEARCH_URL.format(query=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://weixin.sogou.com/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_titles(html: str, limit: int = MAX_ITEMS) -> List[str]:
    titles = []
    for m in re.finditer(r'<a[^>]*uigs="article_title_\d+"[^>]*>(.*?)</a>', html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        t = html_lib.unescape(t).strip()
        if t:
            titles.append(t)
        if len(titles) >= limit:
            break
    return titles


async def _get_titles(query: str, limit: int = MAX_ITEMS) -> Optional[List[str]]:
    """带缓存的热点获取，CACHE_TTL 后自动重新抓取保证时效"""
    now = time.time()
    cached = _cache.get(query)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    html = await asyncio.to_thread(_fetch, query)
    titles = _parse_titles(html, limit)
    if titles:
        _cache[query] = (now, titles)
    return titles or None


def _fmt(title: str, items: List[str], source: str) -> str:
    lines = [title, "━━━━━━━━━━━━"]
    for i, t in enumerate(items, 1):
        lines.append(f"{i}. {t}")
    lines.append("━━━━━━━━━━━━\n来源：微信公众号 · 30分钟自动刷新")
    return "\n".join(lines)


@on_command("/王者热点", "/王者荣耀热点", "/王者资讯")
@plugin_handler
async def handle_wzry(ctx: PluginContext):
    """查看王者荣耀最新热点资讯"""
    await ctx.reply("🔥 正在获取王者荣耀热点...")
    try:
        items = await _get_titles("王者荣耀")
        if not items:
            await ctx.reply("😢 暂时没有获取到热点，请稍后再试")
            return
        await ctx.reply(_fmt("🔥 王者荣耀热点 TOP", items, "weixin"))
    except Exception as e:
        logger.error(f"获取王者荣耀热点失败: {e}")
        await ctx.reply("❌ 获取热点失败，请稍后再试")


@on_command("/王者爆料", "/王者荣耀爆料", "/王者更新")
@plugin_handler
async def handle_wzry_leak(ctx: PluginContext):
    """查看王者荣耀版本更新/新皮肤爆料"""
    await ctx.reply("⚡ 正在搜索王者荣耀最新爆料...")
    try:
        items = await _get_titles("王者荣耀 爆料 更新 皮肤")
        if not items:
            await ctx.reply("😢 暂时没有获取到爆料，请稍后再试")
            return
        await ctx.reply(_fmt("⚡ 王者荣耀最新爆料", items, "weixin"))
    except Exception as e:
        logger.error(f"获取王者荣耀爆料失败: {e}")
        await ctx.reply("❌ 获取爆料失败，请稍后再试")


@on_command("/王者攻略", "/王者荣耀攻略")
@plugin_handler
async def handle_wzry_guide(ctx: PluginContext):
    """查看王者荣耀攻略（可用 /王者攻略 <英雄名> 指定英雄）"""
    rest = (ctx.raw_text or "").strip()
    parts = rest.split(None, 1)
    query = "王者荣耀 攻略"
    if len(parts) > 1:
        query += " " + parts[1].strip()
    await ctx.reply("📖 正在搜索王者荣耀攻略...")
    try:
        items = await _get_titles(query)
        if not items:
            await ctx.reply("😢 暂时没有获取到攻略，请稍后再试")
            return
        hero = f"（{parts[1].strip()}）" if len(parts) > 1 else ""
        await ctx.reply(_fmt(f"📖 王者荣耀攻略{hero}", items, "weixin"))
    except Exception as e:
        logger.error(f"获取王者荣耀攻略失败: {e}")
        await ctx.reply("❌ 获取攻略失败，请稍后再试")
