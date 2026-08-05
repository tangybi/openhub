export interface NewsItem {
  id: string
  title: string
  summary: string
  source: string
  url: string
  category: string
  image_url: string | null
  published_at: string | null
  hot_score: number
  created_at: string
}

export interface NewsListResponse {
  items: NewsItem[]
  total: number
  page: number
  page_size: number
}

export interface CategoryInfo {
  name: string
  count: number
}

export interface AgentInfo {
  name: string
  label: string
  category: string
  available: boolean
  description: string
}

export interface SourceRef {
  title: string
  url: string
  source: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceRef[]
  error?: boolean
}
