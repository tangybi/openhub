"""存储层：JSON 文件存储（新闻）+ Cloudflare R2（粘贴）。

上层业务代码只依赖 NewsStore / PasteStore 接口。
"""

from __future__ import annotations

from ..config import settings
from .base import NewsStore, PasteStore
from .json_store import JsonNewsStore

_store: NewsStore | None = None
_paste_store: PasteStore | None = None
_paste_store_checked = False


def get_store() -> NewsStore:
    global _store
    if _store is None:
        _store = JsonNewsStore(settings.json_data_file)
    return _store


def get_paste_store() -> PasteStore | None:
    """R2 粘贴存储单例；R2 任一配置缺失时返回 None（app 照常启动，路由层抛 503）。"""
    global _paste_store, _paste_store_checked
    if _paste_store_checked:
        return _paste_store
    _paste_store_checked = True
    if not (
        settings.r2_access_key
        and settings.r2_secret_key
        and settings.r2_endpoint
        and settings.r2_bucket
        and settings.r2_public_base_url
    ):
        return None
    from .r2_store import R2PasteStore

    _paste_store = R2PasteStore()
    return _paste_store


__all__ = ["NewsStore", "JsonNewsStore", "get_store", "PasteStore", "R2PasteStore", "get_paste_store"]
