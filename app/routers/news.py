"""新闻列表 / 分类 / 分页 接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import Identity, get_identity
from ..models import NewsItem
from ..storage import get_store

router = APIRouter(prefix="/api/news", tags=["news"])

# 稳定的分类展示顺序；出现未登记分类时动态追加
BASE_CATEGORIES = ["全部", "科技", "财经", "社会", "国际"]


@router.get("")
async def list_news(
    category: str | None = Query(default=None, description="分类，'全部'或省略=不过滤"),
    q: str | None = Query(default=None, description="标题/摘要关键字"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _identity: Identity = Depends(get_identity),  # 惰性注册用户（device_id → 用户+XX）
):
    items = [NewsItem(**it) for it in await get_store().load_items()]
    if category and category != "全部":
        items = [it for it in items if it.category == category]
    if q:
        ql = q.lower()
        items = [
            it for it in items
            if ql in it.title.lower() or ql in (it.summary or "").lower() or ql in it.source.lower()
        ]
    items.sort(key=lambda x: x.hot_score, reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": [it.model_dump(exclude={"raw_summary"}) for it in items[start : start + page_size]],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/categories")
async def list_categories(
    _identity: Identity = Depends(get_identity),  # 惰性注册用户
):
    items = await get_store().load_items()
    counts: dict[str, int] = {}
    for it in items:
        c = it.get("category", "综合") or "综合"
        counts[c] = counts.get(c, 0) + 1
    ordered = []
    seen = set()
    for c in BASE_CATEGORIES:
        if c == "全部":
            continue
        ordered.append({"name": c, "count": counts.get(c, 0)})
        seen.add(c)
    for c, n in counts.items():  # 动态追加未登记分类
        if c not in seen:
            ordered.append({"name": c, "count": n})
    return {"categories": [{"name": "全部", "count": len(items)}, *ordered]}
