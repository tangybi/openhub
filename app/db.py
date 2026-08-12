"""SQLAlchemy 数据层：用户 / 会话 / 消息（Neon Postgres + pgvector）。

身份体系（配合前端）：
- 前端每次请求带 `X-Device-Id` 与 `X-Session-Id` 请求头。
- `device_id` 唯一 → 惰性注册 User（id 形如「用户+XXXX」，随机且保证唯一）。
- `session_id` 由前端生成（uuid，localStorage 持久），后端按 (session_id, user_id) 登记。
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .cache import cache_get, cache_get_json, cache_set, cache_set_json
from .config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "未配置 DATABASE_URL（Neon Postgres 连接串），请填入 app/.env 或部署平台环境变量"
            )
        url = settings.database_url
        # Neon 连接串是 postgresql://；SQLAlchemy 异步引擎需要 postgresql+asyncpg://
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)

        # asyncpg 不接受 URL 里的 sslmode 查询参数，需转成 connect_args['ssl']
        connect_args: dict = {}
        if "sslmode=" in url:
            base, _, query = url.partition("?")
            params = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
            sslmode = params.pop("sslmode", None)
            if sslmode:
                connect_args["ssl"] = sslmode  # 'require' | 'verify-full' | ...
            url = base + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")

        _engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 「用户+XXXX」
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 前端生成的 uuid
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

_PASTE_CODE_ALPHABET = string.ascii_letters + string.digits  # 62 进制字符集


def generate_paste_code(length: int = 8) -> str:
    """随机短码（base62，8 位）；唯一性由主键约束兜底，冲突时外层重试。"""
    return "".join(secrets.choice(_PASTE_CODE_ALPHABET) for _ in range(length))


class Paste(Base):
    __tablename__ = "pastes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)  # 短码，如 "aB3x9K"
    title: Mapped[str] = mapped_column(String(200), default="")
    content_key: Mapped[str] = mapped_column(String(512))  # 正文文本的 R2 key
    language: Mapped[str] = mapped_column(String(32), default="")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delete_token: Mapped[str] = mapped_column(String(64))  # 删除凭证，仅创建时返回
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PasteFile(Base):
    __tablename__ = "paste_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paste_id: Mapped[str] = mapped_column(String(12), ForeignKey("pastes.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(512))  # R2 key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def generate_user_id() -> str:
    """「用户」+ 8 位随机 hex；唯一性由主键约束兜底，冲突时外层重试。"""
    return "用户" + secrets.token_hex(4)


# 身份映射缓存 TTL：device_id → user_id 创建后永不改变，7 天足够
IDENTITY_TTL = 7 * 24 * 3600


async def init_db() -> None:
    """建表（含 pgvector 扩展）。应用启动时调用一次。"""
    from pgvector.sqlalchemy import Vector  # noqa: F401  确保 VECTOR 类型注册

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(device_id: str) -> User:
    """按设备唯一标识惰性注册用户；同 device_id 永远返回同一用户。

    先查 Redis（device_id → user_id），命中直接返回，跳过 Neon 往返
    （Neon 冷连接/跨地域单次查询可达 1-3s）；未命中才查库，成功后写缓存。
    Redis 不可用时静默降级为纯 DB 逻辑。
    """
    cached = await cache_get(f"identity:{device_id}")
    if cached:
        return User(id=cached, device_id=device_id)
    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.execute(select(User).where(User.device_id == device_id))
        user = row.scalar_one_or_none()
        if user is not None:
            await cache_set(f"identity:{device_id}", user.id, ttl=IDENTITY_TTL)
            return user
        for _ in range(5):  # 随机 id 撞主键时重试
            user = User(id=generate_user_id(), device_id=device_id)
            db.add(user)
            try:
                await db.commit()
                await cache_set(f"identity:{device_id}", user.id, ttl=IDENTITY_TTL)
                return user
            except IntegrityError:
                await db.rollback()
    raise RuntimeError("用户注册失败：唯一 id 冲突重试耗尽")


# 会话缓存 TTL：session_id → user_id 创建后永不改变，与身份映射同生命周期
SESSION_TTL = 7 * 24 * 3600


async def ensure_session(session_id: str, user_id: str) -> None:
    """确保会话存在且属于该用户。

    Redis 优先（cache-aside）：命中即返回，完全跳过 Neon 往返；
    未命中才查 DB，成功后将 session_id → user_id 写回 Redis。
    session 一旦创建归属即永久不变，无失效风险。
    """
    cache_key = f"session:{session_id}:user"
    cached = await cache_get(cache_key)
    if cached is not None:
        if cached != user_id:
            raise ValueError("会话不属于当前用户")
        return

    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.execute(select(Session).where(Session.id == session_id))
        existing = row.scalar_one_or_none()
        if existing is not None:
            if existing.user_id != user_id:
                raise ValueError("会话不属于当前用户")
            await cache_set(cache_key, existing.user_id, ttl=SESSION_TTL)
            return
        db.add(Session(id=session_id, user_id=user_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()  # 并发创建，忽略
        await cache_set(cache_key, user_id, ttl=SESSION_TTL)


async def add_message(session_id: str, role: str, content: str) -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        db.add(Message(session_id=session_id, role=role, content=content))
        await db.commit()


MSG_TTL = 15  # 消息缓存 15 秒：不主动失效，靠 TTL 自然过期


async def get_messages(session_id: str, limit: int = 30) -> list[Message]:
    """会话内最近 limit 条消息（按时间升序）。

    Redis 热缓存（短 TTL，15s）：命中直接返回毫秒级；miss 才查 DB 并回填。
    add_message 不碰缓存，新消息最多等 15s 出现在缓存里。
    聊天面板打开的场景命中率极高，用户无感。
    """
    cache_key = f"session:{session_id}:msg:{limit}"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return [Message(role=m["role"], content=m["content"]) for m in cached]

    sm = get_sessionmaker()
    async with sm() as db:
        row = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        messages = list(reversed(row.scalars().all()))

    await cache_set_json(
        cache_key,
        [{"role": m.role, "content": m.content} for m in messages],
        ttl=MSG_TTL,
    )
    return messages
