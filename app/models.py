"""Pydantic 数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """一条热点新闻卡片。"""

    id: str = Field(description="按链接归一化后的稳定 id（sha1 前 16 位）")
    title: str
    summary: str = ""
    source: str
    url: str
    category: str = "综合"
    image_url: str | None = None
    published_at: str | None = None
    hot_score: int = Field(default=50, ge=0, le=100)
    created_at: str = Field(description="入库时间 ISO8601")


class AskRequest(BaseModel):
    """向 Agent 提问的请求体。"""

    question: str = Field(min_length=1, max_length=2000)


class AgentInfo(BaseModel):
    name: str
    label: str
    category: str
    available: bool
    description: str = ""


class SourceRef(BaseModel):
    title: str
    url: str
    source: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef] = []
