"""新闻 Agent：基于热点 + RAG 检索 + 用户记忆 + 会话历史回答用户问题。

每次问答都携带 user_id / session_id：
- session 历史  → 支持多轮追问（会话内）
- mem0 用户记忆 → 跨会话记住用户关注点
- pgvector RAG  → 语义检索相关新闻（超越按热度取的 top-N）
- 热点 top-N   → 当前热度基准

未配置 DEEPSEEK_API_KEY 时降级为纯提示（不调用 LLM）。
"""

from __future__ import annotations

from ..config import settings
from ..db import add_message, get_messages
from ..services.llm import LLMError, chat_completion
from ..services.memory import add_memory, search_memories
from ..services.rag import search_news
from ..storage import get_store
from .base import Agent

_CONTEXT_LIMIT = 15
_SOURCE_LIMIT = 8
_HISTORY_LIMIT = 10
_RAG_TOP_K = 5


class NewsAgent(Agent):
    name = "news"
    label = "热点新闻"
    category = "新闻"
    description = "聚合全网热点，回答关于当前热点事件的提问"

    async def ask(self, question: str, *, user_id: str = "", session_id: str = "") -> dict:
        items = await get_store().load_items()
        top = sorted(items, key=lambda x: x.get("hot_score", 0), reverse=True)[:_CONTEXT_LIMIT]

        # 并行收集三路上下文，各自失败不阻塞问答
        related, memories, history = await self._gather_context(question, user_id, session_id)
        sources = self._build_sources(top, related)

        if not settings.deepseek_api_key:
            return {
                "answer": "新闻 Agent 需要 DEEPSEEK_API_KEY 才能回答问题。"
                "当前已聚合到热点数据，但摘要/问答未启用。",
                "sources": sources,
            }

        context = self._build_prompt_context(history, memories, related, top)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是热点新闻助手。综合「会话历史/用户记忆/相关新闻/当前热点」四部分上下文回答，"
                    "语气简洁客观。能回答的就直接答；上下文覆盖不到时明确说明『当前聚合的新闻暂未覆盖』，不要编造。"
                ),
            },
            {"role": "user", "content": f"{context}\n\n用户问题：{question}"},
        ]
        try:
            answer = await chat_completion(
                messages, temperature=0.4, user_id=user_id, session_id=session_id
            )
        except LLMError as e:
            answer = f"（LLM 暂不可用：{e}）"

        # 落库：会话消息 + 用户长期记忆
        if session_id:
            await add_message(session_id, "user", question)
            await add_message(session_id, "assistant", answer)
        if user_id:
            await add_memory(user_id, f"用户关注的热点问题：{question}")

        return {"answer": answer, "sources": sources}

    async def _gather_context(self, question: str, user_id: str, session_id: str) -> tuple:
        related: list[dict] = []
        memories: list[str] = []
        history: list = []
        try:
            related = await search_news(question, top_k=_RAG_TOP_K)
        except Exception:
            related = []
        try:
            memories = await search_memories(user_id, question)
        except Exception:
            memories = []
        if session_id:
            try:
                history = await get_messages(session_id, limit=_HISTORY_LIMIT)
            except Exception:
                history = []
        return related, memories, history

    def _build_prompt_context(self, history, memories, related, top) -> str:
        blocks: list[str] = []
        if history:
            lines = [
                f"{'用户' if m.role == 'user' else '助手'}: {m.content[:200]}" for m in history
            ]
            blocks.append("【本会话历史】\n" + "\n".join(lines))
        if memories:
            blocks.append("【该用户的长期记忆】\n" + "\n".join(f"- {m}" for m in memories))
        if related:
            blocks.append(
                "【与问题相关的新闻检索】\n"
                + "\n".join(
                    f"- [{r['title']}]({r['url']}) 来源{r['source']} · {r['summary'][:150]}"
                    for r in related
                )
            )
        if top:
            blocks.append(
                "【当前热点】\n"
                + "\n".join(
                    f"- [{it.get('title', '')}]({it.get('url', '')}) "
                    f"来源{it.get('source', '')} · {it.get('summary', '')[:150]}"
                    for it in top
                )
            )
        return "\n\n".join(blocks)

    def _build_sources(self, top: list[dict], related: list[dict]) -> list[dict]:
        seen: set[str] = set()
        merged: list[dict] = []
        for it in [*related, *top]:
            url = it.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(
                {"title": it.get("title", ""), "url": url, "source": it.get("source", "")}
            )
            if len(merged) >= _SOURCE_LIMIT:
                break
        return merged
