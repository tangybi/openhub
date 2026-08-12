"""应用配置：全部从环境变量读取，本地开发由 app/.env 提供（python-dotenv）。

部署时在平台（如 FastAPICloud）配置同名环境变量，app/.env 会被忽略。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv 加载 app/.env（部署时无需，变量来自平台配置）
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover
    pass


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# app/ 目录（config.py 所在处）。数据文件固定在 app/data/news.json，与运行目录无关。
APP_DIR = Path(__file__).resolve().parent


@dataclass
class Settings:
    # LLM（DeepSeek，OpenAI 兼容协议）
    deepseek_api_key: str = field(default_factory=lambda: _get("DEEPSEEK_API_KEY"))
    deepseek_model: str = field(default_factory=lambda: _get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    deepseek_base_url: str = field(
        default_factory=lambda: _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )

    # 云端数据库（Neon Postgres + pgvector）：users/sessions/messages + RAG 向量 + mem0 记忆
    database_url: str = field(default_factory=lambda: _get("DATABASE_URL"))

    # Redis 缓存（身份映射/新闻列表等热点数据）；未配置时自动降级为直连，不影响功能
    redis_url: str = field(default_factory=lambda: _get("REDIS_URL"))

    # 对象存储：Cloudflare R2（S3 兼容，boto3）。粘贴正文与附件落 R2，短链接 302 直出。
    r2_access_key: str = field(default_factory=lambda: _get("R2_ACCESS_KEY"))
    r2_secret_key: str = field(default_factory=lambda: _get("R2_SECRET_KEY"))
    r2_endpoint: str = field(
        default_factory=lambda: _get(
            "R2_ENDPOINT", "https://<accountid>.r2.cloudflarestorage.com"
        )
    )
    r2_bucket: str = field(default_factory=lambda: _get("R2_BUCKET"))
    r2_public_base_url: str = field(default_factory=lambda: _get("R2_PUBLIC_BASE_URL"))

    # 应用公开访问基础地址（分享短链接前缀，如 https://api.example.com）。
    # 留空时按请求 Host 推导（本地开发/直连部署无需配置）。
    app_base_url: str = field(default_factory=lambda: _get("APP_BASE_URL"))

    # embedding 向量化（硅基流动 BGE-M3；DeepSeek 无 embedding 接口，RAG/mem0 都需要）
    embedding_api_key: str = field(default_factory=lambda: _get("EMBEDDING_API_KEY"))
    embedding_base_url: str = field(
        default_factory=lambda: _get("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
    )
    embedding_model: str = field(default_factory=lambda: _get("EMBEDDING_MODEL", "BAAI/bge-m3"))

    # 存储：JSON 文件（app/data/news.json，可进 git 作为种子数据基线）
    json_data_file: str = field(
        default_factory=lambda: _get("JSON_DATA_FILE", str(APP_DIR / "data" / "news.json"))
    )

    # 抓取保护：配置后 /api/cron/ingest 需要 Authorization: Bearer <secret>
    cron_secret: str = field(default_factory=lambda: _get("CRON_SECRET"))

    # 看板日志目录（默认 app/log，绝对路径与运行目录无关；可被 LOG_DIR 覆盖）。
    # dashboard_secret 配置后 GET /api/dashboard/* 需要 Authorization: Bearer <secret>
    log_dir: str = field(default_factory=lambda: _get("LOG_DIR", str(APP_DIR / "log")))
    dashboard_secret: str = field(default_factory=lambda: _get("DASHBOARD_SECRET"))

    # 允许跨域的前端地址
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in _get(
                "CORS_ORIGINS",
                "https://openhub.allberry.cn,http://localhost:5173,http://localhost:4173",
            ).split(",")
            if o.strip()
        ]
    )

    # RSS 抓取参数
    ingest_per_feed: int = int(_get("INGEST_PER_FEED", "10"))
    ingest_max_items: int = int(_get("INGEST_MAX_ITEMS", "120"))
    summarize_concurrency: int = int(_get("SUMMARIZE_CONCURRENCY", "5"))


settings = Settings()
