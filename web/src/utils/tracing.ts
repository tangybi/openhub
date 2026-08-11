// 前端 OpenTelemetry 埋点。
//
// 方案：标准 OTel（WebTracerProvider + span + W3C traceparent 传播），
// 但项目没有 OTLP collector，所以用自定义 SpanExporter 把已结束的 span 批量
// POST 到后端 /api/trace 落日志。trace_id 通过 W3C traceparent 请求头跨端共享：
// 前端生成根 span → fetch 时注入 traceparent → 后端 FastAPI 插桩继承同一 trace_id，
// 日志里 grep trace_id 即可串联「前端交互 → 后端请求 → LLM → 记忆」全链路。
//
// 浏览器没有 zone.js，async 上下文不会自动跨 await 传递，所以全部显式传父 span
// （startChildSpan）与显式注入（injectTraceparent），不依赖活跃上下文。

import { context, propagation, trace, SpanStatusCode } from '@opentelemetry/api'
import type { Attributes, Span, Tracer } from '@opentelemetry/api'
import { ExportResultCode, W3CTraceContextPropagator } from '@opentelemetry/core'
import type { ExportResult } from '@opentelemetry/core'
import {
  BatchSpanProcessor,
  StackContextManager,
  WebTracerProvider,
} from '@opentelemetry/sdk-trace-web'
import type { ReadableSpan, SpanExporter } from '@opentelemetry/sdk-trace-web'
import { API_BASE } from './apiBase'

let _tracer: Tracer | null = null

/** 前端全局 Tracer（须先调用 initTracing）。 */
function tracer(): Tracer {
  if (!_tracer) throw new Error('initTracing() must be called before creating spans')
  return _tracer
}

/** 把 span 序列化成后端 /api/trace 能消费的 JSON 结构。 */
function serializeSpan(s: ReadableSpan) {
  const ctx = s.spanContext()
  const toMs = (h: [number, number]) => h[0] * 1000 + h[1] / 1e6
  return {
    trace_id: ctx.traceId,
    span_id: ctx.spanId,
    parent_span_id: s.parentSpanContext?.spanId ?? null,
    name: s.name,
    duration_ms: toMs(s.duration),
    status: s.status.code,
    attributes: s.attributes,
    events: s.events.map((e) => ({ name: e.name, attributes: e.attributes })),
  }
}

/** 自定义 SpanExporter：把已结束的 span 批量 POST 到后端 /api/trace 落日志。 */
class TraceSinkExporter implements SpanExporter {
  export(spans: ReadableSpan[], resultCallback: (result: ExportResult) => void): void {
    const payload = spans.map(serializeSpan)
    fetch(`${API_BASE}/api/trace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spans: payload }),
    })
      .then(() => resultCallback({ code: ExportResultCode.SUCCESS }))
      .catch(() => resultCallback({ code: ExportResultCode.FAILED }))
  }

  shutdown(): Promise<void> {
    return Promise.resolve()
  }
}

/** 初始化前端追踪（幂等）：WebTracerProvider + W3C 传播 + 自定义导出器。 */
export function initTracing(): void {
  // v2：span 处理器在构造参数里配置（spanProcessors）
  const provider = new WebTracerProvider({
    spanProcessors: [new BatchSpanProcessor(new TraceSinkExporter())],
  })
  provider.register({ contextManager: new StackContextManager() })
  propagation.setGlobalPropagator(new W3CTraceContextPropagator())
  _tracer = trace.getTracer('hotscope-web')
}

/** 创建一个 span（无父级时为根 span，有自己的 trace_id）。 */
export function startSpan(name: string, attrs?: Attributes): Span {
  return tracer().startSpan(name, { attributes: attrs })
}

/** 在业务 span 内执行异步任务：正常自动置 OK，抛错自动记 ERROR 并重新抛出。 */
export async function runWithSpan<T>(
  name: string,
  attrs: Attributes,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  const span = startSpan(name, attrs)
  try {
    const result = await fn(span)
    span.setStatus({ code: SpanStatusCode.OK })
    return result
  } catch (err) {
    recordSpanError(span, err instanceof Error ? err.message : String(err))
    throw err
  } finally {
    span.end()
  }
}

/** 以 parent 为父级创建子 span（显式传父，浏览器无 zone.js 也不丢关联）。 */
export function startChildSpan(parent: Span, name: string, attrs?: Attributes): Span {
  // v2：startSpan 不再接受 parent 选项，改由 context.with 提供活跃父上下文
  const ctx = trace.setSpan(context.active(), parent)
  return context.with(ctx, () => tracer().startSpan(name, { attributes: attrs }))
}

/** 把 span 的 W3C traceparent 注入请求头，让后端请求继承同一 trace_id。 */
export function injectTraceparent(span: Span, headers: Record<string, string>): void {
  propagation.inject(trace.setSpan(context.active(), span), headers)
}

/** 标记 span 出错 + 记录异常（业务层在「已处理的错误分支」手动调用）。 */
export function recordSpanError(span: Span, message: string): void {
  span.recordException(new Error(message))
  span.setStatus({ code: SpanStatusCode.ERROR, message })
}
