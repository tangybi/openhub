"""Agent 体系：可扩展的分类 Agent 注册表。

新增一个 Agent 只需三步：
1. 在 app/agents/ 下新建模块，继承 Agent 实现 ask()
2. 在 __init__.py 里实例化并加入 AGENTS 字典
3. 前端 web/src/agents.ts 里登记 label/icon
后端会自动暴露 GET /api/agents 与 POST /api/agents/{name}/ask。
"""

from __future__ import annotations

from .base import Agent
from .news_agent import NewsAgent
from .placeholder import BrandAgent, FinanceAgent, LearningAgent

AGENTS: dict[str, Agent] = {
    "news": NewsAgent(),
    "finance": FinanceAgent(),
    "brand": BrandAgent(),
    "learning": LearningAgent(),
}

__all__ = ["Agent", "AGENTS", "NewsAgent"]
