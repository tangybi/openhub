"""占位 Agent：金融分析 / 品牌竞品 / 学习。available=False，前端显示占位页。"""

from __future__ import annotations

from .base import Agent


class _Placeholder(Agent):
    available = False

    async def ask(self, question: str, *, user_id: str = "", session_id: str = "") -> dict:
        return {
            "answer": f"「{self.label}」Agent 尚未实现，敬请期待。",
            "sources": [],
        }


class FinanceAgent(_Placeholder):
    name = "finance"
    label = "金融分析"
    category = "金融"
    description = "金融数据分析（占位，规划中）"


class BrandAgent(_Placeholder):
    name = "brand"
    label = "品牌竞品"
    category = "品牌"
    description = "品牌竞品分析（占位，规划中）"


class LearningAgent(_Placeholder):
    name = "learning"
    label = "学习"
    category = "学习"
    description = "学习型 Agent（占位，规划中）"
