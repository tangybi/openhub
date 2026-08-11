"""粘贴业务层：短码、删除凭证、R2 上传/读取、过期判断。

DB 访问走 get_sessionmaker()（模块级函数，路由层不碰 session）；对象存储走
storage.get_paste_store()。R2 未配置时抛 PasteStorageError，路由层转 503。
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import UploadFile
from sqlalchemy import delete as sa_delete, select, update
from sqlalchemy.exc import IntegrityError

from ..db import Paste, PasteFile, _now, generate_paste_code, get_sessionmaker
from ..logger_config import get_logger
from ..storage import PasteStore, get_paste_store

logger = get_logger()

MAX_CONTENT_BYTES = 1_000_000  # 正文文本上限 1MB
MAX_FILE_BYTES = 10 * 1024 * 1024  # 单附件 10MB
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 正文 + 全部附件 20MB
MAX_FILES = 20
MAX_EXPIRES_IN = 31_536_000  # 最长 1 年（秒）


class PasteStorageError(Exception):
    """R2 未配置或对象存储操作失败。"""


class PasteLimitError(Exception):
    """附件/正文大小或数量超限（路由层转 413）。"""


def _require_store() -> PasteStore:
    store = get_paste_store()
    if store is None:
        raise PasteStorageError(
            "对象存储 R2 未配置，请配置 R2_ACCESS_KEY / R2_SECRET_KEY / "
            "R2_ENDPOINT / R2_BUCKET / R2_PUBLIC_BASE_URL"
        )
    return store


def _sanitize_filename(name: str) -> str:
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name).strip("._")[:80]
    return name or "file"


async def _read_limited(up: UploadFile, limit: int) -> bytes:
    """1MB 分块读取附件；超限立即抛 PasteLimitError（避免大文件占满内存）。"""
    data = bytearray()
    while True:
        chunk = await up.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise PasteLimitError(f"附件超出 {MAX_FILE_BYTES // (1024 * 1024)}MB 大小限制")
    return bytes(data)


async def create_paste(
    *,
    title: str,
    language: str,
    content_bytes: bytes,
    files: list[UploadFile],  # 附件直接传 UploadFile；流在短码重试循环前统一读取
    expires_in: int,  # 秒；0 = 永不过期
    user_id: str = "",  # 可选创建者身份（仅日志）
) -> dict:
    """生成短码 → 落 DB 行拿 code → 传 R2 → 提交。R2 上传失败则回滚 R2 对象 + DB 行。

    返回 {"code", "url", "delete_token", "expires_at", "files"}：
    expires_at 为 ISO8601 或 None；files 为 [{name, content_type, size, url}, ...]（空列表 = 无附件）。
    """
    store = _require_store()
    # UploadFile 的流只能读一次：统一在短码重试循环前读取成 bytes 并做大小校验
    file_payloads: list[dict] = []
    total = len(content_bytes)
    for up in files:
        data = await _read_limited(up, MAX_FILE_BYTES)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise PasteLimitError("正文 + 附件超出 20MB 总大小限制")
        file_payloads.append(
            {
                "name": up.filename or "file",
                "content_type": up.content_type or "application/octet-stream",
                "data": data,
            }
        )

    for _ in range(5):  # 短码撞主键时重试
        code = generate_paste_code()
        token = secrets.token_urlsafe(24)
        expires_at = (_now() + timedelta(seconds=expires_in)) if expires_in > 0 else None
        content_key = f"pastes/{code}/content"
        file_keys = [
            f"pastes/{code}/files/{i}-{_sanitize_filename(f['name'])}"
            for i, f in enumerate(file_payloads)
        ]

        sm = get_sessionmaker()
        async with sm() as db:
            db.add(
                Paste(
                    id=code,
                    title=title[:200],
                    content_key=content_key,
                    language=language[:32],
                    expires_at=expires_at,
                    delete_token=token,
                )
            )
            for f, key in zip(file_payloads, file_keys):
                db.add(
                    PasteFile(
                        paste_id=code,
                        name=f["name"][:255],
                        content_type=f["content_type"][:128],
                        size=len(f["data"]),
                        key=key,
                    )
                )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue  # 短码冲突，换一个

        # 落库成功 → 传 R2；失败则回滚
        try:
            content_type = "text/markdown; charset=utf-8" if language else "text/plain; charset=utf-8"
            await store.put_bytes(content_key, content_bytes, content_type)
            for f, key in zip(file_payloads, file_keys):
                await store.put_bytes(
                    key, f["data"], f.get("content_type") or "application/octet-stream"
                )
        except Exception:
            logger.exception("paste 对象上传失败[code=%s]，回滚", code)
            await _rollback_upload(code, content_key, file_keys)
            raise PasteStorageError("对象存储上传失败，请重试")

        logger.info("paste 创建[code=%s title=%s user=%s files=%d]", code, title[:50], user_id, len(files))
        return {
            "code": code,
            "url": store.public_url(content_key),
            "delete_token": token,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "files": [
                {
                    "name": f["name"][:255],
                    "content_type": f["content_type"][:128],
                    "size": len(f["data"]),
                    "url": store.public_url(key),
                }
                for f, key in zip(file_payloads, file_keys)
            ],
        }
    raise PasteStorageError("短码生成失败：唯一性冲突重试耗尽")


async def _rollback_upload(code: str, content_key: str, file_keys: list[str]) -> None:
    """创建失败时回滚：尽力删 R2 对象 + 删 DB 行。"""
    store = get_paste_store()
    if store is not None:
        for key in [content_key, *file_keys]:
            try:
                await store.delete_object(key)
            except Exception:
                logger.warning("回滚删除 R2 对象失败[key=%s]", key)
    try:
        sm = get_sessionmaker()
        async with sm() as db:
            await db.execute(sa_delete(PasteFile).where(PasteFile.paste_id == code))
            await db.execute(sa_delete(Paste).where(Paste.id == code))
            await db.commit()
    except Exception:
        logger.warning("回滚删除 DB 行失败[code=%s]", code)


async def get_paste(code: str) -> Paste | None:
    """按短码取粘贴行。"""
    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.execute(select(Paste).where(Paste.id == code))
        return row.scalar_one_or_none()


async def get_paste_files(code: str) -> list[PasteFile]:
    """附件行（按 id 升序）。"""
    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.execute(
            select(PasteFile).where(PasteFile.paste_id == code).order_by(PasteFile.id)
        )
        return list(row.scalars().all())


def is_expired(paste: Paste) -> bool:
    return paste.expires_at is not None and paste.expires_at <= _now()


async def increment_view_count(code: str) -> None:
    """view_count 原子 +1（仅公开短链访问时调用）。"""
    sm = get_sessionmaker()
    async with sm() as db:
        await db.execute(
            update(Paste).where(Paste.id == code).values(view_count=Paste.view_count + 1)
        )
        await db.commit()


async def load_content(store: PasteStore, content_key: str) -> str:
    """从 R2 读正文文本，decode utf-8（errors='replace'）；对象缺失返回空串。"""
    data = await store.get_bytes(content_key)
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace")


async def delete_paste(code: str, delete_token: str) -> bool:
    """删除：token 校验 → 删 R2 对象（尽力，失败仅告警）→ 删 DB 行。返回是否删成功。

    粘贴不存在返回 False；token 不匹配 raise ValueError（路由层转 403）。
    """
    paste = await get_paste(code)
    if paste is None:
        return False
    if not secrets.compare_digest(paste.delete_token, delete_token):
        raise ValueError("删除凭证不正确")
    files = await get_paste_files(code)

    store = get_paste_store()
    if store is not None:
        for key in [paste.content_key, *(f.key for f in files)]:
            try:
                await store.delete_object(key)
            except Exception:
                logger.warning("删除 R2 对象失败[key=%s]", key)

    sm = get_sessionmaker()
    async with sm() as db:
        await db.execute(sa_delete(PasteFile).where(PasteFile.paste_id == code))
        await db.execute(sa_delete(Paste).where(Paste.id == code))
        await db.commit()
    logger.info("paste 删除[code=%s]", code)
    return True
