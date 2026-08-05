"""存储层：JSON 文件存储（app/data/news.json）。

上层业务代码只依赖 NewsStore 接口。
"""

from __future__ import annotations

from ..config import settings
from .base import NewsStore
from .json_store import JsonNewsStore

_store: NewsStore | None = None


def get_store() -> NewsStore:
    global _store
    if _store is None:
        _store = JsonNewsStore(settings.json_data_file)
    return _store


__all__ = ["NewsStore", "JsonNewsStore", "get_store"]
