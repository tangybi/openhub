"""DeepSeek 摘要 + 热度分。

对每条新抓取的新闻生成：中文摘要（~80 字）+ 热度分（0-100）+ 纠偏分类。
DeepSeek 不可用时降级：用 feed 自带摘要（去 HTML 标签）+ 启发式热度分。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .llm import LLMError, chat_json


def strip_html(text: str) -> str:
    """去掉 HTML 标签、压缩空白。"""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def heuristic_hot_score(published_at: str | None, source: str) -> int:
    """无 LLM 时的兜底热度分：基础 50 + 时效加成 + 头部源加成。"""
    score = 50
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if age_hours <= 2:
                score += 25
            elif age_hours <= 12:
                score += 15
            elif age_hours <= 24:
                score += 8
        except ValueError:
            pass
    if source in {"少数派", "36氪", "虎嗅", "澎湃新闻", "IT之家"}:
        score += 5
    return max(0, min(99, score))


async def summarize_item(item: dict) -> dict:
    """生成 {summary, hot_score, category}。LLM 失败时回退启发式。"""
    prompt = (
        "你是中文热点新闻编辑。给定一条新闻，输出 JSON：\n"
        "{\"summary\": \"中文摘要，80 字以内，客观精炼\", "
        "\"hot_score\": 0到100的整数（全网热度判断）, "
        "\"category\": \"分类，从[科技,财经,社会,国际]中选\"}\n\n"
        f"标题：{item['title']}\n"
        f"原文摘要：{strip_html(item.get('raw_summary', ''))[:500]}\n"
        f"来源：{item['source']}\n"
        f"发布时间：{item.get('published_at') or '未知'}\n"
        "只输出 JSON 对象，不要多余文字。"
    )
    try:
        data = await chat_json([{"role": "user", "content": prompt}])
        hot = int(data.get("hot_score", 50))
        return {
            "summary": strip_html(str(data.get("summary", ""))) or "暂无摘要",
            "hot_score": max(0, min(100, hot)),
            "category": str(data.get("category", item["category"])).strip() or item["category"],
        }
    except (LLMError, ValueError):
        return {
            "summary": strip_html(item.get("raw_summary", ""))[:120] or "暂无摘要",
            "hot_score": heuristic_hot_score(item.get("published_at"), item["source"]),
            "category": item["category"],
        }
