"""新闻 Agent：基于热点 + RAG 检索 + 用户记忆 + 会话历史回答用户问题。

每次问答都携带 user_id / session_id：
- session 历史  → 支持多轮追问（会话内）
- mem0 用户记忆 → 跨会话记住用户关注点
- pgvector RAG  → 语义检索相关新闻（超越按热度取的 top-N）
- 热点 top-N   → 当前热度基准

未配置 DEEPSEEK_API_KEY 时降级为纯提示（不调用 LLM）。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from ..logger_config import get_logger

from ..config import settings
from ..db import get_messages
from ..services.llm import LLMError, chat_completion, chat_completion_stream
from ..services.memory import add_memory, search_memories
from ..services.rag import search_news
from ..storage import get_store
from .base import Agent, AgentEvent

_CONTEXT_LIMIT = 15
_SOURCE_LIMIT = 8
_HISTORY_LIMIT = 10
_RAG_TOP_K = 5
logger = get_logger()

# 后台落库任务跟踪：持有引用防 GC 中途取消
_pending_persist_tasks: set[asyncio.Task] = set()


async def _persist(question: str, answer: str, user_id: str, session_id: str) -> None:
    """后台落库：仅用户长期记忆（会话消息由统一 Ask 入口落库，避免重复）。失败静默。"""
    try:
        if user_id:
            await add_memory(user_id, f"用户关注的热点问题：{question}")
    except Exception:
        logger.exception("后台落库失败")


def _schedule_persist(question: str, answer: str, user_id: str, session_id: str) -> None:
    """把落库调度到后台任务，不阻塞 done 帧送达与连接关闭。

    mem0 add_memory 内部要做 embeddings + LLM + pgvector 写入，串行执行会拖住流式收尾，
    导致前端在回答显示完后还长时间停留在「发送中」。
    """
    try:
        task = asyncio.create_task(_persist(question, answer, user_id, session_id))
    except RuntimeError:  # 事件循环不可用（极少数关闭场景）
        return
    _pending_persist_tasks.add(task)
    task.add_done_callback(_pending_persist_tasks.discard)

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
            logger.warning("LLM 调用失败，返回友好提示：%s", e)
            answer = "抱歉，暂时没能生成回答，请换个问法再试一次。"
        if not answer or not answer.strip():
            answer = "抱歉，暂时没能生成回答，请换个问法再试一次。"

        # 用户长期记忆（会话消息由统一 Ask 入口落库）
        if user_id:
            await add_memory(user_id, f"用户关注的热点问题：{question}")

        return {"answer": answer, "sources": sources}

    async def ask_stream(
        self, question: str, *, user_id: str = "", session_id: str = ""
    ) -> AsyncIterator[AgentEvent]:
        """流式回答：先发 sources，再逐段 yield 正文增量。

        复用 ask() 的上下文收集；LLM 失败/空内容时降级为友好提示（已有部分正文则不再叠加）。
        流结束后（含客户端中途断开）尽力落库会话消息与用户记忆。
        """
        items = await get_store().load_items()
        top = sorted(items, key=lambda x: x.get("hot_score", 0), reverse=True)[:_CONTEXT_LIMIT]

        # 并行收集三路上下文，各自失败不阻塞问答
        related, memories, history = await self._gather_context(question, user_id, session_id)
        sources = self._build_sources(top, related)
        yield ("sources", sources)

        if not settings.deepseek_api_key:
            yield (
                "delta",
                "新闻 Agent 需要 DEEPSEEK_API_KEY 才能回答问题。"
                "当前已聚合到热点数据，但摘要/问答未启用。",
            )
            yield ("done", None)
            return

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

        answer_parts: list[str] = []
        got_any = False
        try:
            async for delta in chat_completion_stream(
                messages, temperature=0.4, user_id=user_id, session_id=session_id
            ):
                got_any = True
                answer_parts.append(delta)
                yield ("delta", delta)
        except LLMError as e:
            logger.warning("LLM 流式调用失败，返回友好提示：%s", e)
            if not got_any:  # 已有部分正文时不叠加提示语
                fallback = "抱歉，暂时没能生成回答，请换个问法再试一次。"
                answer_parts.append(fallback)
                yield ("delta", fallback)

        try:
            answer = "".join(answer_parts)
            if not answer.strip():
                answer = "抱歉，暂时没能生成回答，请换个问法再试一次。"
                answer_parts.append(answer)
                yield ("delta", answer)
            logger.info("LLM 回答[user=%s session=%s]：%s", user_id or "-", session_id or "-", answer)
            yield ("done", None)
        finally:
            # 落库挪到后台任务，不再阻塞 done 帧送达与连接关闭
            _schedule_persist(question, "".join(answer_parts) or answer, user_id, session_id)

    async def _gather_context(self, question: str, user_id: str, session_id: str) -> tuple:
        """并行收集三路上下文：RAG 检索 / 记忆检索 / 会话历史。

        三路互不依赖，串行会累加首字节前的耗时；并行只取决于最慢一路。
        search_news / search_memories 内部已各自兜底返回 []，gather 不会因此失败。
        """
        async def _history() -> list:
            if not session_id:
                return []
            try:
                return await get_messages(session_id, limit=_HISTORY_LIMIT)
            except Exception:
                return []

        try:
            related, memories, history = await asyncio.gather(
                search_news(question, top_k=_RAG_TOP_K),
                search_memories(user_id, question),
                _history(),
            )
        except Exception:
            return [], [], []
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
