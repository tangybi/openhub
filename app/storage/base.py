"""NewsStore 接口：新闻条目的持久化。"""

from __future__ import annotations

import abc


class NewsStore(abc.ABC):
    @abc.abstractmethod
    async def load_items(self) -> list[dict]:
        """读取全部新闻条目（dict 列表）。"""

    @abc.abstractmethod
    async def save_items(self, items: list[dict]) -> None:
        """整体覆盖写入全部新闻条目。"""
