"""本地 JSON 文件存储（开发环境）。data/news.json 可进 git，作为种子数据基线。

热点数据在 Redis 缓存：load 优先读缓存（文件兜底），save 后主动失效，
避免每个请求都重复读盘。Redis 不可用时自动退化为纯文件读写。
"""

from __future__ import annotations

import asyncio
import json
import os

from .base import NewsStore
from ..cache import cache_delete, cache_get_json, cache_set_json


class JsonNewsStore(NewsStore):
    _ITEMS_KEY = "news:items"
    _ITEMS_TTL = 3600  # 1 小时兜底；save_items 主动失效保证新鲜

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def load_items(self) -> list[dict]:
        cached = await cache_get_json(self._ITEMS_KEY)
        if cached is not None:
            return cached
        if not os.path.exists(self.path):
            return []
        loop = asyncio.get_running_loop()

        def _read() -> list:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []

        items = await loop.run_in_executor(None, _read)
        await cache_set_json(self._ITEMS_KEY, items, ttl=self._ITEMS_TTL)
        return items

    async def save_items(self, items: list[dict]) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

            def _write() -> None:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)

            await loop.run_in_executor(None, _write)
        await cache_delete(self._ITEMS_KEY)  # 失效缓存，下次 load 重新读盘
