"""看板分析：从日志文件统计 UV / PV / 接口响应时长 / 异常报错详情。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import settings
from ..models import DashboardStats
from ..services import logstats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _resolve_range(days: int | None, start: str | None, end: str | None) -> tuple[date, date]:
    """解析时间范围：有 start/end 用显式区间（必须成对），否则按 days 取末尾 N 天。"""
    today = datetime.now().date()
    if start or end:
        if not (start and end):
            raise HTTPException(status_code=400, detail="start 与 end 必须同时提供（YYYY-MM-DD）")
        try:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        if s > e:
            raise HTTPException(status_code=400, detail="start 不能晚于 end")
        return s, e
    n = days or 7
    return today - timedelta(days=n - 1), today


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    request: Request,
    days: int | None = Query(default=None, ge=1, le=90),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    include_errors: bool = Query(default=True),
):
    """看板统计聚合。配置了 DASHBOARD_SECRET 时要求 Authorization: Bearer <secret>。"""
    if settings.dashboard_secret:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {settings.dashboard_secret}":
            raise HTTPException(status_code=401, detail="dashboard 密钥校验失败")
    s, e = _resolve_range(days, start, end)
    return logstats.compute_stats(s, e, include_errors=include_errors)
