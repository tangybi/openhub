"""本地 JSON 文件存储（开发环境）。data/news.json 可进 git，作为种子数据基线。"""

from __future__ import annotations

import asyncio
import json
import os

from .base import NewsStore


class JsonNewsStore(NewsStore):
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def load_items(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        loop = asyncio.get_running_loop()

        def _read() -> list:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []

        return await loop.run_in_executor(None, _read)

    async def save_items(self, items: list[dict]) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

            def _write() -> None:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)

            await loop.run_in_executor(None, _write)
