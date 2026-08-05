"""RAG 检索：把聚合新闻向量化存入 pgvector，问答时检索相关新闻增强上下文。

表 `news_embeddings`（BGE-M3 → VECTOR(1024)）。抓取入库后调用 `reindex_news` 同步索引；
`search_news` 首次调用时会自动补建索引（对当前已有新闻）。
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from ..config import settings
from ..db import Base, get_sessionmaker
from .embedding import embed_batch, embed_one

EMBED_DIM = 1024
_TOP_K = 5

_indexed = False


class NewsEmbedding(Base):
    __tablename__ = "news_embeddings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 与新闻 id 一致
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)  # 摘要
    url: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="综合")
    hot_score: Mapped[int] = mapped_column(Integer, default=50)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))


async def reindex_news(items: list[dict]) -> dict:
    """把新闻列表 upsert 进向量库，返回统计。embedding 失败时抛 EmbeddingError。"""
    if not items or not settings.embedding_api_key:
        return {"indexed": 0}
    texts = [f"{it.get('title', '')}\n{it.get('summary', '')}" for it in items]
    vectors = await embed_batch(texts)

    sm = get_sessionmaker()
    async with sm() as db:
        for it, vec in zip(items, vectors):
            row = NewsEmbedding(
                id=it["id"],
                title=it.get("title", ""),
                content=it.get("summary", "") or "",
                url=it.get("url", ""),
                source=it.get("source", ""),
                category=it.get("category", "综合"),
                hot_score=it.get("hot_score", 50),
                embedding=vec,
            )
            await db.merge(row)
        await db.commit()
    return {"indexed": len(items)}


async def search_news(query: str, top_k: int = _TOP_K) -> list[dict]:
    """按语义相似度检索相关新闻。未配置/失败时返回空列表。"""
    if not settings.embedding_api_key:
        return []
    try:
        await _ensure_indexed()
        vector = await embed_one(query)
        sm = get_sessionmaker()
        async with sm() as db:
            stmt = (
                select(NewsEmbedding)
                .order_by(NewsEmbedding.embedding.cosine_distance(vector))
                .limit(top_k)
            )
            rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "summary": r.content,
                "url": r.url,
                "source": r.source,
                "category": r.category,
                "hot_score": r.hot_score,
            }
            for r in rows
        ]
    except Exception:
        return []


async def _ensure_indexed() -> None:
    """向量库为空时，对当前已有新闻补建一次索引（进程内只触发一次）。"""
    global _indexed
    if _indexed:
        return
    sm = get_sessionmaker()
    async with sm() as db:
        count = await db.execute(select(func.count(NewsEmbedding.id)))
        if (count.scalar() or 0) > 0:
            _indexed = True
            return
    from ..storage import get_store

    items = await get_store().load_items()
    if items:
        await reindex_news(items)
    _indexed = True
