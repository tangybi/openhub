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


class PasteStore(abc.ABC):
    """粘贴对象存储接口（R2 直出）。"""

    @abc.abstractmethod
    async def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        cache_control: str = "public, max-age=3600",
    ) -> None:
        """写对象（覆盖语义）。"""

    @abc.abstractmethod
    async def get_bytes(self, key: str) -> bytes | None:
        """读对象；对象不存在返回 None。"""

    @abc.abstractmethod
    async def delete_object(self, key: str) -> None:
        """删对象；不存在时静默。"""

    @abc.abstractmethod
    def public_url(self, key: str) -> str:
        """由 key 拼出自定义域名的可公开访问 URL。"""
