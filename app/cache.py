"""Redis 缓存工具：身份映射、新闻列表等热点数据。

- 未配置 REDIS_URL 或连接失败时全部静默降级（读返回 None / 写跳过），不影响主流程。
- 单例连接池；decode_responses=True 直接返回 str。
- 云端部署适配：支持 rediss://（TLS，如 Upstash/Redis Cloud）；限制连接数并设短超时，
  线上 Redis 抖动/不可用时快速失败回退到 DB，不会拖住请求。
"""

from __future__ import annotations

import json
from typing import Any

from .config import settings

# 连接池上限：Serverless Redis（Upstash 等免费档）并发连接有限，10 足够缓存读写
_POOL_MAX = 10
# 短超时：Redis 只是加速层，连不上/慢就立刻降级，不让请求被它拖死
_CONNECT_TIMEOUT = 2
_IO_TIMEOUT = 2

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.redis_url:
            return None
        try:
            from redis.asyncio import Redis

            _client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=_POOL_MAX,
                socket_connect_timeout=_CONNECT_TIMEOUT,
                socket_timeout=_IO_TIMEOUT,
            )
        except Exception:
            _client = None  # redis 库缺失 / 配置非法：降级为无缓存
    return _client


async def cache_get(key: str) -> str | None:
    client = _get_client()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception:
        return None


async def cache_get_json(key: str) -> Any | None:
    raw = await cache_get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def cache_set(key: str, value: str, ttl: int | None = None) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl)
    except Exception:
        pass


async def cache_set_json(key: str, value: Any, ttl: int | None = None) -> None:
    await cache_set(key, json.dumps(value, ensure_ascii=False), ttl=ttl)


async def cache_delete(key: str) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        pass
