"""Pydantic 数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """一条热点新闻卡片。"""

    id: str = Field(description="按链接归一化后的稳定 id（sha1 前 16 位）")
    title: str
    summary: str = ""
    source: str
    url: str
    category: str = "综合"
    image_url: str | None = None
    published_at: str | None = None
    hot_score: int = Field(default=50, ge=0, le=100)
    created_at: str = Field(description="入库时间 ISO8601")


class AskRequest(BaseModel):
    """向 Agent 提问的请求体。"""

    question: str = Field(min_length=1, max_length=2000)


class AgentInfo(BaseModel):
    name: str
    label: str
    category: str
    available: bool
    description: str = ""


class SourceRef(BaseModel):
    title: str
    url: str
    source: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef] = []


class PasteFileInfo(BaseModel):
    name: str
    content_type: str
    size: int
    url: str


class PasteLink(BaseModel):
    """一条可独立分享的短链。id 唯一：content=正文，f-{i}=第 i 个附件。"""

    id: str
    name: str  # 展示名：正文 / 附件文件名
    url: str  # 应用内短链（302 到对应 R2 直出），供分享


class PasteCreateResponse(BaseModel):
    code: str
    url: str  # R2 正文直出 URL（绝对地址）
    short_url: str  # 应用内短链接（302 到 R2 直出），供分享
    delete_token: str
    expires_at: str | None = None
    files: list[PasteFileInfo] = []  # 本次已上传的附件信息（创建时可选，可为空；JSON 响应不能用 UploadFile）
    links: list[PasteLink] = []  # 短链列表：正文 + 每个附件各一条，可独立分享


class PasteDetailResponse(BaseModel):
    code: str
    title: str
    language: str
    content: str  # 从 R2 读取的正文文本（编辑器回填）
    expires_at: str | None = None
    view_count: int
    created_at: str  # ISO8601
    files: list[PasteFileInfo] = []
    links: list[PasteLink] = []  # 短链列表：正文 + 每个附件各一条，可独立分享


class DateRange(BaseModel):
    """看板统计的时间范围。"""

    start: str  # YYYY-MM-DD（含）
    end: str
    days: int


class OverviewStat(BaseModel):
    """看板总览指标（从日志聚合）。"""

    uv: int = 0
    uv_source: str = "none"  # device_id | user_token | none
    user_count: int = 0  # 去重 user= 用户数（始终算，与 uv_source 无关）
    pv: int = 0
    ask_count: int = 0
    total_requests: int = 0
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    max_latency_ms: float | None = None
    error_count: int = 0
    error_rate: float = 0.0  # 后端错误请求 / 总请求 * 100
    llm_calls: int = 0  # LLM 调用次数
    prompt_tokens: int = 0  # LLM 输入 tokens
    completion_tokens: int = 0  # LLM 输出 tokens
    embed_tokens: int = 0  # embedding（向量化）tokens
    total_tokens: int = 0  # prompt + completion + embed


class EndpointStat(BaseModel):
    """单个接口（method+route）的响应时长与错误统计。"""

    method: str
    route: str
    count: int = 0
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    max_latency_ms: float | None = None
    error_count: int = 0


class ErrorDetail(BaseModel):
    """一条错误请求 / 前端异常详情。"""

    time: str  # YYYY-MM-DD HH:MM:SS（来自日志行前缀）
    source: str  # backend | frontend
    method: str = ""
    route: str = ""
    status_code: int | None = None
    span_status: str = ""
    request_body: str = ""
    response_body: str = ""
    message: str = ""  # 前端异常的 msg
    trace_id: str = ""


class DashboardStats(BaseModel):
    """看板统计聚合结果。"""

    range: DateRange
    overview: OverviewStat
    endpoints: list[EndpointStat] = []
    errors: list[ErrorDetail] = []
    files_parsed: list[str] = []
    log_dir: str = ""
