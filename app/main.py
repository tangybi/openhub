"""HotScope 主应用。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logger_config import setup_logging
from .otel import init_tracing

from . import __version__
from .config import settings
from .routers import agents, cron, news, pastes, trace


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 建表（Neon pgvector）。DB 未配置时不阻塞启动，实际请求会报清晰错误。
    try:
        from .db import init_db

        await init_db()
    except Exception:
        pass
    yield


app = FastAPI(title="HotScope 热点聚合 API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news.router)
app.include_router(agents.router)
app.include_router(cron.router)
app.include_router(trace.router)
app.include_router(pastes.router)
app.include_router(pastes.public_router)
setup_logging()
init_tracing(app)

@app.get("/")
async def root():
    return {"name": "HotScope 热点聚合", "version": __version__, "docs": "/docs"}
