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

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface PasteFileInfo {
  name: string
  content_type: string
  size: number
  url: string // R2 直出 URL（绝对地址）
}

export interface PasteLink {
  id: string // content=正文 / f-{i}=第 i 个附件
  name: string // 展示名：正文 / 附件文件名
  url: string // 应用内短链（302 到对应 R2 直出），供分享
}

export interface PasteCreateResponse {
  code: string
  url: string // R2 正文直出 URL（绝对地址）
  short_url: string // 兼容字段：正文短链（= links 里 id=content 那条）
  delete_token: string
  expires_at: string | null
  files: PasteFileInfo[] // 本次已上传的附件信息（可为空）
  links: PasteLink[] // 短链列表：正文 + 每个附件各一条，可独立分享
}

export interface PasteDetailResponse {
  code: string
  title: string
  language: string
  content: string
  expires_at: string | null
  view_count: number
  created_at: string
  files: PasteFileInfo[]
  links: PasteLink[]
}

export interface DateRange {
  start: string
  end: string
  days: number
}

export interface OverviewStat {
  uv: number
  uv_source: 'device_id' | 'user_token' | 'none'
  user_count: number
  pv: number
  ask_count: number
  total_requests: number
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  max_latency_ms: number | null
  error_count: number
  error_rate: number
  llm_calls: number
  prompt_tokens: number
  completion_tokens: number
  embed_tokens: number
  total_tokens: number
}

export interface EndpointStat {
  method: string
  route: string
  count: number
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  max_latency_ms: number | null
  error_count: number
}

export interface ErrorDetail {
  time: string
  source: 'backend' | 'frontend'
  method: string
  route: string
  status_code: number | null
  span_status: string
  request_body: string
  response_body: string
  message: string
  trace_id: string
}

export interface DashboardStats {
  range: DateRange
  overview: OverviewStat
  endpoints: EndpointStat[]
  errors: ErrorDetail[]
  files_parsed: string[]
  log_dir: string
}
