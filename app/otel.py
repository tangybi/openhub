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

    FastAPIInstrumentor().instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    _tracing_initialized = True
    logger.info("OpenTelemetry 追踪已启用（FastAPI + httpx 插桩，span 写入日志）")
