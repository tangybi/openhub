"""Agent 基类。"""

from __future__ import annotations

import abc
from typing import Any, AsyncIterator

# 流式事件：(类型, 数据)。取值：
#   ("sources", list[dict])  → 来源列表（LLM 调用前就已知，先发）
#   ("delta", str)           → 一段正文增量（逐字输出）
#   ("done", None)           → 流正常结束
AgentEvent = tuple[str, Any]


class Agent(abc.ABC):
    name: str
    label: str
    category: str
    description: str = ""

    @property
    def available(self) -> bool:
        """该 Agent 是否已实现（占位 Agent 返回 False）。"""
        return True

    @abc.abstractmethod
    async def ask(self, question: str, *, user_id: str = "", session_id: str = "") -> dict:
        """回答用户问题。

        user_id / session_id 由身份层注入，Agent 内部调用 LLM/记忆/RAG 时都必须透传。
        返回 {"answer": str, "sources": [...]}。
        """

    async def ask_stream(
        self, question: str, *, user_id: str = "", session_id: str = ""
    ) -> AsyncIterator[AgentEvent]:
        """默认流式实现：包装 :meth:`ask` 一次性产出。

        未覆写的 Agent（如占位 Agent）走这里：先发 sources，再整段 delta，最后 done。
        需要真正逐字输出的 Agent（如 NewsAgent）覆写本方法。
        """
        result = await self.ask(question, user_id=user_id, session_id=session_id)
        yield ("sources", result.get("sources", []))
        answer = result.get("answer", "")
        if answer:
            yield ("delta", answer)
        yield ("done", None)
