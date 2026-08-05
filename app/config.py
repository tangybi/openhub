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

    # 允许跨域的前端地址
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in _get(
                "CORS_ORIGINS",
                "http://localhost:5173,http://localhost:4173",
            ).split(",")
            if o.strip()
        ]
    )

    # RSS 抓取参数
    ingest_per_feed: int = int(_get("INGEST_PER_FEED", "10"))
    ingest_max_items: int = int(_get("INGEST_MAX_ITEMS", "120"))
    summarize_concurrency: int = int(_get("SUMMARIZE_CONCURRENCY", "5"))


settings = Settings()
