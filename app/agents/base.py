"""Agent 基类。"""

from __future__ import annotations

import abc


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
