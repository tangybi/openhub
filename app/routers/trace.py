"""前端埋点接收：把浏览器侧的 OTel span 以 JSON 形式落日志。

前端 ``WebTracerProvider`` 的自定义 SpanExporter 会把 span 序列化后 POST 到这里，
与后端日志共用同一日志文件；trace_id 由 W3C ``traceparent`` 跨端共享，
可按 trace_id 一条命令 grep 出「前端交互 → 后端请求 → LLM 调用 → 记忆检索」全链路。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..logger_config import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.post("")
async def ingest_trace(request: Request):
    """接收前端 span 列表并逐条写日志。非 dict/坏 JSON 时静默降级，不影响主流程。"""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "reason": "bad json"}

    spans = body.get("spans", []) if isinstance(body, dict) else body
    if not isinstance(spans, list):
        return {"ok": False, "reason": "spans not a list"}

    for s in spans:
        _log_frontend_span(s)
    return {"ok": True, "count": len(spans)}


def _log_frontend_span(s) -> None:
    trace_id = s.get("trace_id") or "-"
    span_id = s.get("span_id") or "-"
    parent_id = s.get("parent_span_id") or "-"
    name = s.get("name") or "?"
    status = s.get("status") or 0
    dur = s.get("duration_ms")
    dur_s = f"{dur:.1f}ms" if isinstance(dur, (int, float)) else "-"
    attrs = s.get("attributes") or {}
    attr_s = " ".join(f"{k}={v}" for k, v in attrs.items())
    logger.info(
        "前端SPAN name=%s trace=%s span=%s parent=%s dur=%s status=%s %s",
        name, trace_id, span_id, parent_id, dur_s, status, attr_s,
    )
    # 异常事件单独 warning 落一条，方便检索
    for ev in s.get("events") or []:
        if ev.get("name") in ("exception", "error"):
            a = ev.get("attributes") or {}
            logger.warning(
                "前端异常 name=%s trace=%s type=%s msg=%s",
                name, trace_id,
                a.get("exception.type") or "-",
                a.get("exception.message") or "-",
            )
