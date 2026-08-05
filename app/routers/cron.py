"""抓取入口：RSS 定时/手动抓取。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..services.rss_ingest import ingest_once

router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.api_route("/ingest", methods=["GET", "POST"])
async def cron_ingest(request: Request):
    """抓取一次 RSS 并入库。

    前端「抓取最新」按钮用 POST 手动触发；定时任务也可用 GET 调用。
    配置了 CRON_SECRET 时要求 Authorization: Bearer <secret>。
    """
    if settings.cron_secret:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {settings.cron_secret}":
            raise HTTPException(status_code=401, detail="cron 密钥校验失败")
    return await ingest_once()
