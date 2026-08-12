"""OpenTelemetry 统一初始化 + 日志导出器。

职责：
- 启用 FastAPI / httpx 自动插桩：每个 HTTP 请求、LLM 调用都会生成 span，
  其 trace_id / span_id 经 :class:`logger_config.TraceContextFilter` 自动落到每条日志上。
- span 本体（耗时/属性）通过 :class:`LogSpanExporter` 以 ``SPAN ...`` 行写入同一日志文件，
  便于按 trace_id 串联「前端埋点 / 后端请求 / LLM 调用 / 记忆检索」全链路。
- 前端通过 W3C ``traceparent`` 请求头把 trace_id 带进来，跨端共享同一条链路。

项目暂无 OTLP collector，所以 span 不导出到远端，而是落本地日志文件；
将来接 collector 时只需把 :class:`LogSpanExporter` 换成 OTLPSpanExporter。
"""

from __future__ import annotations

from opentelemetry import trace as otel_trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExportResult,
    SpanExporter,
)
from opentelemetry.sdk.trace.export import SpanProcessor
from collections.abc import Sequence
from typing import Any, Optional

from starlette.requests import Request
from starlette.responses import Response

from .logger_config import get_logger

logger = get_logger()

_tracing_initialized = False


class _AsgiFilterProcessor(SpanProcessor):
    """丢弃 ASGI 内部子 span（http receive / http send / response.body 等）。

    FastAPI 插桩会给流式响应的**每一帧**都生成一个 ``http.response.body`` 子 span，
    逐帧写日志既慢又刷屏。这里只保留请求级 span 与 httpx 的 LLM/embedding span，
    保证跨端 trace 关联不变，同时去掉流式逐帧开销。
    """

    def __init__(self, inner: SpanProcessor) -> None:
        self._inner = inner

    def on_start(self, span, parent_context) -> None:
        self._inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if span.attributes and span.attributes.get("asgi.event.type"):
            return
        self._inner.on_end(span)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class LogSpanExporter(SpanExporter):
    """把每个 span 以一行日志写入共享日志文件（与 TraceContextFilter 互补）。"""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
            parent_id = format(span.parent.span_id, "016x") if span.parent else "-"
            dur_ms = (span.end_time - span.start_time) / 1e6
            attrs = dict(span.attributes or {})
            attr_s = " ".join(f"{k}={v}" for k, v in attrs.items())
            logger.info(
                "SPAN name=%s trace=%s span=%s parent=%s dur=%.1fms status=%s %s",
                span.name,
                trace_id,
                span_id,
                parent_id,
                dur_ms,
                span.status.status_code.name,
                attr_s,
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def _oneline(s: str) -> str:
    """把可能含换行的正文压成一行（保持 span 日志一行一条，避免破坏 grep/解析）。"""
    return " ".join(s.split())


def _truncate(s: str, limit: int = 2000) -> str:
    return s if len(s) <= limit else s[:limit] + f"…(+{len(s) - limit} chars)"


_BODY_READ_LIMIT = 4 * 1024  # 请求体超过该字节数就不整读上报（避免大 JSON 缓冲进内存）


def _add_error_capture_middleware(app) -> None:
    """错误请求上报：非 200/201 的响应，把请求体与错误响应体写入 span 属性。

    必须在 :func:`FastAPIInstrumentor.instrument_app` 之前调用，否则 span 不在
    中间件的上下文里，取不到当前请求 span。
    - multipart 上传跳过请求体（二进制且可能很大）
    - 请求体按 content-length 判大小，超过 _BODY_READ_LIMIT 不整读上报（端点自行消费）
    - 记录的 body 都经 _truncate 截断到 2000 字符，日志保持一行一条
    - 正常 2xx（含 SSE 流）直接透传不消费 body；仅错误响应整读后按原样重建
    """
    @app.middleware("http")
    async def _capture(request: Request, call_next):
        want_body = "multipart/form-data" not in request.headers.get("content-type", "")
        # 只有声明了 content-length 且足够小的请求体才整读上报；大请求体不读，
        # 交给端点自行消费，避免中间件把大块 JSON 缓冲进内存。
        body_bytes = b""
        cl = request.headers.get("content-length", "")
        if want_body and cl.isdigit() and int(cl) <= _BODY_READ_LIMIT:
            # 读请求体：Starlette 会缓存到 request._body，端点后续 request.json() 等照常可读
            body_bytes = await request.body()
        response = await call_next(request)

        span = otel_trace.get_current_span()
        if (
            span is None
            or not span.is_recording()
            or response.status_code in (200, 201)
        ):
            return response

        if body_bytes:
            text = body_bytes.decode("utf-8", "replace")
            span.set_attribute("http.request.body", _truncate(_oneline(text)))

        # BaseHTTPMiddleware 把响应包成 _StreamingResponse（无 .body），
        # 消费 body_iterator 取错误响应体，再按原样重建响应透传给客户端。
        chunks = [chunk async for chunk in response.body_iterator]
        err_bytes = b"".join(chunks)
        if err_bytes:
            err = err_bytes.decode("utf-8", "replace")
            span.set_attribute("http.response.body", _truncate(_oneline(err)))
        response = Response(
            content=err_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
        return response


def init_tracing(app) -> None:
    """初始化全局 TracerProvider，并为 FastAPI / httpx 启用插桩。幂等，可安全重复调用。"""
    global _tracing_initialized
    if _tracing_initialized:
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: "hotscoapp-backend"}))
    provider.add_span_processor(
        _AsgiFilterProcessor(SimpleSpanProcessor(LogSpanExporter()))
    )
    otel_trace.set_tracer_provider(provider)

    _add_error_capture_middleware(app)
    FastAPIInstrumentor().instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    _tracing_initialized = True
    logger.info("OpenTelemetry 追踪已启用（FastAPI + httpx 插桩，span 写入日志）")
