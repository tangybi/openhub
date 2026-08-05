"""FastAPI 依赖：请求身份解析。

前端每个请求带 `X-Device-Id`（浏览器生成的设备唯一码，localStorage 持久）；
后端据此惰性注册用户（device_id 唯一 → 「用户+XXXX」），返回 Identity 注入路由。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from .db import get_or_create_user


@dataclass
class Identity:
    device_id: str
    user_id: str


async def get_identity(x_device_id: str | None = Header(default=None)) -> Identity:
    device_id = (x_device_id or "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="缺少 X-Device-Id 请求头")
    try:
        user = await get_or_create_user(device_id)
    except RuntimeError as e:  # DATABASE_URL 未配置 / 连接失败
        raise HTTPException(status_code=503, detail=str(e))
    return Identity(device_id=device_id, user_id=user.id)
