import type { AgentInfo, CategoryInfo, NewsListResponse, SourceRef } from './types'

// 生产环境后端域名：web/.env.production 里配 VITE_API_BASE_URL（或 Vercel 环境变量）。
// 本地开发留空 → 走 vite.config.ts 的 /api 代理（127.0.0.1:8000）。
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || `请求失败：${res.status}`)
  }
  return data as T
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

export async function triggerIngest(): Promise<{ new: number; total: number }> {
  return request('/api/cron/ingest', { method: 'POST' })
}
