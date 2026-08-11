import type {
  AgentInfo,
  CategoryInfo,
  ChatHistoryMessage,
  NewsListResponse,
  PasteCreateResponse,
  PasteDetailResponse,
  SourceRef,
} from './types'
import { getDeviceId, getSessionId } from './utils/identity'
import { API_BASE } from './utils/apiBase'
import {
  injectTraceparent,
  recordSpanError,
  runWithSpan,
  startChildSpan,
  startSpan,
} from './utils/tracing'

const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n) + '…' : s)

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const method = options?.method ?? 'GET'
  // 每个 HTTP 请求一个 span：注入 traceparent 让后端继承同一 trace_id，出错自动记 ERROR。
  return runWithSpan('http.request', { method, http_url: url }, async (span) => {
    // 身份头：device_id 唯一标识（后端惰性注册用户），session_id 标记会话。
    // FormData 由浏览器自动设 multipart boundary，不能手动指定 Content-Type。
    const headers: Record<string, string> = {
      ...(options?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      'X-Device-Id': getDeviceId(),
      'X-Session-Id': getSessionId(),
      ...(options?.headers as Record<string, string> | undefined),
    }
    injectTraceparent(span, headers)
    const res = await fetch(`${API_BASE}${url}`, { ...options, headers })
    span.setAttributes({ http_status: res.status })
    const data = await res.json().catch(() => null)
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || `请求失败：${res.status}`)
    }
    return data as T
  })
}

export async function fetchNews(params: {
  category?: string
  q?: string
  page?: number
  page_size?: number
}): Promise<NewsListResponse> {
  const query = new URLSearchParams()
  if (params.category && params.category !== '全部') query.set('category', params.category)
  if (params.q) query.set('q', params.q)
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  return request(`/api/news?${query.toString()}`)
}

export async function fetchCategories(): Promise<CategoryInfo[]> {
  const data = await request<{ categories: CategoryInfo[] }>('/api/news/categories')
  return data.categories
}

export async function fetchAgents(): Promise<AgentInfo[]> {
  const data = await request<{ agents: AgentInfo[] }>('/api/agents')
  return data.agents
}

export async function askAgent(
  name: string,
  question: string,
): Promise<{ answer: string; sources: SourceRef[] }> {
  return request(`/api/agents/${encodeURIComponent(name)}/ask`, {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}

export async function createPaste(payload: {
  title: string
  language: string
  content: string
  expires_in: number
  files: File[]
}): Promise<PasteCreateResponse> {
  const fd = new FormData()
  fd.append('title', payload.title)
  fd.append('language', payload.language)
  fd.append('content', payload.content)
  fd.append('expires_in', String(payload.expires_in))
  // 前端限制：没选文件就完全不发 files 字段（走后端 default=[]）。
  // 后端 files 是声明式可选入参，显式发空串 `files=` 会 422——这里保证永不产生空 files 部分。
  if (payload.files.length) {
    for (const f of payload.files) fd.append('files', f)
  }
  return request('/api/pastes', { method: 'POST', body: fd })
}

export async function fetchPasteDetail(code: string): Promise<PasteDetailResponse> {
  return request(`/api/pastes/${encodeURIComponent(code)}`)
}

export async function deletePaste(
  code: string,
  token: string,
): Promise<{ deleted: boolean; code: string }> {
  return request(`/api/pastes/${encodeURIComponent(code)}?token=${encodeURIComponent(token)}`, {
    method: 'DELETE',
  })
}

export interface AskAgentStreamHandlers {
  onSources?: (sources: SourceRef[]) => void
  onDelta?: (text: string) => void
  onDone?: () => void
  onError?: (message: string) => void
}

/** 流式提问底层：POST SSE 并回调 onSources/onDelta/onDone/onError。网络错误与中途断开都走 onError。 */
async function streamAsk(
  url: string,
  question: string,
  handlers: AskAgentStreamHandlers,
  attrs: { agent: string; http_url: string },
): Promise<void> {
  // ask 根 span：业务事件「提问」，含 agent / 问题 / 流状态 / 来源数 / 回答长度等属性。
  // 手动管理生命周期（不用 runWithSpan）：流错误走 onError 而不是抛异常，需手动标 ERROR。
  const askSpan = startSpan('ask', { agent: attrs.agent, question: truncate(question, 200) })

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
    'X-Session-Id': getSessionId(),
  }
  const httpSpan = startChildSpan(askSpan, 'http.request', {
    method: 'POST',
    http_url: attrs.http_url,
  })
  injectTraceparent(httpSpan, headers)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ question }),
    })
  } catch {
    httpSpan.end()
    recordSpanError(askSpan, '网络错误：无法连接服务器')
    askSpan.setAttributes({ stream_status: 'network_error' })
    askSpan.end()
    handlers.onError?.('网络错误：无法连接服务器')
    return
  }
  httpSpan.setAttributes({ http_status: res.status })
  httpSpan.end()

  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => null)
    recordSpanError(askSpan, detail?.detail || `请求失败：${res.status}`)
    askSpan.setAttributes({ stream_status: 'error', http_status: res.status })
    askSpan.end()
    handlers.onError?.(detail?.detail || `请求失败：${res.status}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let sourcesCount = 0
  let answerLength = 0
  let errored = false

  const dispatch = (frame: string) => {
    const lines = frame.replace(/\r\n/g, '\n').split('\n')
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    const raw = dataLines.join('\n')
    if (!raw) return
    switch (event) {
      case 'sources':
        try {
          const parsed = JSON.parse(raw) as SourceRef[]
          sourcesCount = parsed.length
          handlers.onSources?.(parsed)
        } catch {
          /* 忽略坏帧 */
        }
        break
      case 'delta':
        try {
          const text = JSON.parse(raw) as string
          answerLength += text.length
          handlers.onDelta?.(text)
        } catch {
          /* 忽略坏帧 */
        }
        break
      case 'done':
        handlers.onDone?.()
        break
      case 'error': {
        let message = raw
        try {
          message = JSON.parse(raw).message ?? raw
        } catch {
          /* 保留原文 */
        }
        errored = true
        recordSpanError(askSpan, message)
        askSpan.setAttributes({ stream_status: 'error', error_msg: message })
        handlers.onError?.(message)
        break
      }
      default:
        break
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        dispatch(buffer.slice(0, sep))
        buffer = buffer.slice(sep + 2)
        sep = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer) // 收尾未以 \n\n 结尾的帧
  } catch (e: any) {
    errored = true
    const msg = e?.message || '连接中断，回答不完整'
    recordSpanError(askSpan, msg)
    askSpan.setAttributes({ stream_status: 'error', error_msg: msg })
    handlers.onError?.(msg)
  }

  // 流结束：汇总业务属性（done/error、来源数、回答长度、空回答）
  askSpan.setAttributes({
    stream_status: errored ? 'error' : 'done',
    sources_count: sourcesCount,
    answer_length: answerLength,
    empty_answer: answerLength === 0,
  })
  askSpan.setStatus({ code: errored ? 2 : 0 })
  askSpan.end()
}

/** 直调指定 Agent 流式提问（保留给按名调用场景）。 */
export async function askAgentStream(
  name: string,
  question: string,
  handlers: AskAgentStreamHandlers,
): Promise<void> {
  return streamAsk(`/api/agents/${encodeURIComponent(name)}/ask/stream`, question, handlers, {
    agent: name,
    http_url: `/api/agents/${name}/ask/stream`,
  })
}

/** 统一 Ask 流式提问：后端按领域自动路由到专家 Agent（后端判不出时通用回答兜底）。 */
export async function askRouterStream(
  question: string,
  handlers: AskAgentStreamHandlers,
): Promise<void> {
  return streamAsk('/api/agents/ask/stream', question, handlers, {
    agent: 'router',
    http_url: '/api/agents/ask/stream',
  })
}

export async function fetchChatHistory(): Promise<ChatHistoryMessage[]> {
  const data = await request<{ messages: ChatHistoryMessage[] }>('/api/agents/history')
  return data.messages
}

export async function triggerIngest(): Promise<{ new: number; total: number }> {
  return request('/api/cron/ingest', { method: 'POST' })
}
