"""Embedding 封装：硅基流动 BGE-M3（OpenAI 兼容 /embeddings 接口）。

DeepSeek 没有 embedding 接口，RAG 检索与 mem0 记忆的向量化都走这里。
BGE-M3 输出 1024 维，对应 app/db.py 与 rag.py 里的 VECTOR(1024)。
"""

from __future__ import annotations

import httpx

from ..config import settings


class EmbeddingError(Exception):
    """embedding 调用失败（未配置 key / 网络 / 服务错误）。"""


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量向量化，返回与输入等长的向量列表。"""
    if not settings.embedding_api_key:
        raise EmbeddingError("未配置 EMBEDDING_API_KEY（硅基流动），请填入 app/.env")
    if not texts:
        return []

    url = settings.embedding_base_url.rstrip("/") + "/embeddings"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={"model": settings.embedding_model, "input": texts},
        )

    if r.status_code != 200:
        raise EmbeddingError(f"embedding 调用失败: HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    try:
        items = sorted(data["data"], key=lambda x: x["index"])
        return [it["embedding"] for it in items]
    except (KeyError, TypeError, IndexError):
        raise EmbeddingError(f"embedding 返回格式异常: {str(data)[:300]}")


async def embed_one(text: str) -> list[float]:
    """单条向量化。"""
    if not text.strip():
        raise EmbeddingError("embedding 输入为空")
    return (await embed_batch([text]))[0]
