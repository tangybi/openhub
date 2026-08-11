"""mem0 用户长期记忆：按 user_id 存取跨会话记忆。

- 向量后端：pgvector（Neon，`mem0_memories` collection），不落本地文件
- LLM：DeepSeek（OpenAI 兼容）
- embedding：硅基流动 BGE-M3（OpenAI 兼容 /embeddings）
"""

from __future__ import annotations

import asyncio
import os

# 禁用 mem0 的 PostHog 遥测：遥测会发起阻塞网络调用（feature flags 等），
# 每次记忆检索/写入都拖慢数秒。必须在 mem0 初始化前设置。
os.environ.setdefault("MEM0_TELEMETRY", "False")

from mem0 import Memory

from ..logger_config import get_logger

from ..config import settings

logger = get_logger()

# BGE-M3 输出维度
EMBED_DIM = 1024


def _mem0_config() -> dict:
    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "connection_string": settings.database_url,
                "collection_name": "mem0_memories",
                "embedding_model_dims": EMBED_DIM,
                "sslmode": "require",
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings.deepseek_model,
                "api_key": settings.deepseek_api_key,
                "openai_base_url": settings.deepseek_base_url,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": settings.embedding_model,
                "api_key": settings.embedding_api_key,
                "openai_base_url": settings.embedding_base_url,
            },
        },
        "history_db_path": "",
    }


async def search_memories(user_id: str, query: str, top_k: int = 5) -> list[str]:
    """检索用户长期记忆（跨会话）。配置缺失或失败时返回空列表，不阻塞问答。"""
    if not (settings.deepseek_api_key and settings.embedding_api_key and settings.database_url):
        logger.info("记忆检索跳过：未配置 deepseek/embedding/database（user=%s query=%s）", user_id or "-", query)
        return []
    try:
        memories = await asyncio.to_thread(_search_sync, user_id, query, top_k)
        logger.info("记忆检索[user=%s query=%s]：命中 %d 条", user_id or "-", query, len(memories))
        for mem in memories:
            logger.info("  · %s", mem)
        return memories
    except Exception:
        logger.exception("记忆检索失败（user=%s query=%s）", user_id or "-", query)
        return []


def _search_sync(user_id: str, query: str, top_k: int) -> list[str]:
    memory = Memory.from_config(_mem0_config())
    # mem0 2.x：search 返回 {"results": [...]}，user_id 走 filters
    result = memory.search(query, filters={"user_id": user_id}, limit=top_k)
    return [r.get("memory", "") for r in (result or {}).get("results", [])]


async def add_memory(user_id: str, content: str) -> None:
    """写入一条用户记忆（内部用 LLM 提炼事实）。失败静默，不阻塞主流程。"""
    if not content.strip() or not (settings.deepseek_api_key and settings.embedding_api_key):
        return
    try:
        await asyncio.to_thread(_add_sync, user_id, content)
    except Exception:
        pass


def _add_sync(user_id: str, content: str) -> None:
    memory = Memory.from_config(_mem0_config())
    memory.add(content, user_id=user_id)
