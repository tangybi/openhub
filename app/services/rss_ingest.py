"""RSS 抓取 → 去重 → DeepSeek 摘要 → 入库 的全链路。

幂等：以新闻链接的归一化 sha1 作为 id，已入库的条目跳过不重复摘要。
按 hot_score 降序裁剪到 INGEST_MAX_ITEMS 条。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx

from ..config import settings
from ..storage import get_store
from .feeds import get_feed_targets
from .rag import reindex_news
from .summarizer import summarize_item

_HTML_RE = re.compile(r"<[^>]+>")


def _normalize_url(url: str) -> str:
    """去掉 utm 等追踪参数后归一化链接。"""
    try:
        parts = urlparse(url)
        query = "&".join(
            kv for kv in parts.query.split("&") if kv and not kv.split("=")[0].startswith(("utm_", "from"))
        )
        return parts._replace(query=query).geturl()
    except Exception:
        return url


def _item_id(url: str, source: str, title: str) -> str:
    return hashlib.sha1(f"{_normalize_url(url)}|{source}|{title}".encode("utf-8")).hexdigest()[:16]


def _parse_time(value) -> str | None:
    """feedparser 的 published_parsed/updated_parsed 是 time.struct_time。"""
    if not value:
        return None
    try:
        dt = datetime(*value[:6])  # struct_time 支持切片
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _first_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for m in getattr(entry, key, []) or []:
            if m.get("url"):
                return m["url"]
    if getattr(entry, "enclosures", None):
        for e in entry.enclosures:
            if str(e.get("type", "")).startswith("image"):
                return e.get("href")
    if getattr(entry, "image", None):
        return entry.image.get("href")
    # 从正文 html 里提取首张图片
    for field in ("summary", "content"):
        html = getattr(entry, field, None)
        if isinstance(html, list):
            html = html[0].get("value", "") if html else ""
        if isinstance(html, str):
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
            if m:
                return m.group(1)
    return None


def _clean_title(text: str) -> str:
    """清洗标题：去掉 U+FFFD 替换符与控制字符（部分源 feed 编码有杂讯）。"""
    return "".join(ch for ch in text if ch >= " " and ch != "�").strip()


def entry_to_item(entry, feed: dict) -> dict:
    raw_summary = getattr(entry, "summary", "") or ""
    if isinstance(raw_summary, list):
        raw_summary = raw_summary[0].get("value", "") if raw_summary else ""
    title = _clean_title(_HTML_RE.sub("", getattr(entry, "title", "") or "")) or "未命名"
    url = _normalize_url(getattr(entry, "link", "") or "")
    published_at = _parse_time(getattr(entry, "published_parsed", None)) or _parse_time(
        getattr(entry, "updated_parsed", None)
    )
    return {
        "id": _item_id(url, feed["name"], title),
        "title": title,
        "summary": "",
        "source": feed["name"],
        "url": url,
        "category": feed["category"],
        "image_url": _first_image(entry),
        "published_at": published_at,
        "hot_score": 50,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw_summary": _HTML_RE.sub("", raw_summary)[:800],
    }


async def ingest_once() -> dict:
    """执行一次抓取入库，返回统计。单个源失败不影响整体。"""
    store = get_store()
    existing = await store.load_items()
    merged: dict[str, dict] = {it["id"]: it for it in existing}

    stats = {"fetched": 0, "new": 0, "skipped": 0, "errors": []}
    sem = asyncio.Semaphore(settings.summarize_concurrency)

    async def _summarize(item: dict) -> dict:
        async with sem:
            return await summarize_item(item)

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for feed in get_feed_targets():
            try:
                r = await client.get(feed["url"])
                r.raise_for_status()
                parsed = feedparser.parse(r.content)
                pending: list[dict] = []
                for entry in parsed.entries[: settings.ingest_per_feed]:
                    item = entry_to_item(entry, feed)
                    stats["fetched"] += 1
                    if item["id"] in merged:
                        stats["skipped"] += 1
                        continue
                    pending.append(item)
                if not pending:
                    continue
                enriched = await asyncio.gather(*[_summarize(it) for it in pending])
                for item, extra in zip(pending, enriched):
                    item.update(extra)
                    merged[item["id"]] = item
                    stats["new"] += 1
            except Exception as e:  # 单源容错
                stats["errors"].append(f'{feed["name"]}: {e}')

    items = sorted(merged.values(), key=lambda x: x.get("hot_score", 0), reverse=True)
    if len(items) > settings.ingest_max_items:
        items = items[: settings.ingest_max_items]
    await store.save_items(items)
    stats["total"] = len(items)

    # 同步向量索引（RAG 检索用）。embedding 未配置/失败时仅记录，不阻塞抓取。
    try:
        stats["indexed"] = (await reindex_news(items)).get("indexed", 0)
    except Exception as e:  # pragma: no cover
        stats["indexed_error"] = str(e)
    return stats


async def run_ingest_script() -> None:
    """本地/命令行入口（python -m app.services.rss_ingest）。"""
    stats = await ingest_once()
    print(stats)


if __name__ == "__main__":
    asyncio.run(run_ingest_script())
