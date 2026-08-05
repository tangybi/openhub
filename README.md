# HotScope 热点聚合

前后端分离的热点聚合应用：FastAPI 后端定时从 **RSS** 抓取热点新闻，
DeepSeek 生成中文摘要与热度分，Vue3 + Vite 前端瀑布流展示，并带一个
「问 Agent」对话入口 —— 支持**多轮会话 + 用户长期记忆 + RAG 新闻检索**。
头部 Tab 预留了 **金融分析 / 品牌竞品 / 学习** 三个扩展 Agent 槽位。

## 架构

```text
┌──────────────┐ X-Device-Id  ┌──────────────────────────┐   HTTP   ┌──────────┐
│  Vue3+Vite   │  X-Session-Id│  FastAPI (app/)          │ ───────▶ │ 原生 RSS  │
│  web/        │ ────────────▶│  · 身份/会话：惰性注册     │          │ DIRECT_  │
└──────────────┘              │  · agents：会话历史+记忆   │          │ FEEDS    │
                              │    +RAG 检索+热点 → LLM   │          └──────────┘
                              │  · embedding：硅基流动 BGE-M3│
                              └───────────┬────────────────┘
                                          ▼
                              ┌──────────────────────────┐
                              │ Neon Postgres (pgvector)  │ users / sessions / messages
                              │                          │ news_embeddings（新闻向量）
                              │                          │ mem0 记忆向量
                              └──────────────────────────┘
```

- **后端**（`app/`）：自包含 uv 项目。
- **数据全云端**：用户/会话/消息 + 新闻向量 + mem0 记忆都存 Neon Postgres（pgvector）。
  FastAPICloud 无本地文件持久化，因此**不落盘**，云端可任意扩缩容。
- **记忆与检索**：mem0（用户长期记忆）+ pgvector RAG（新闻语义检索），embedding 走硅基流动 BGE-M3。

## 身份与会话

- 前端首次访问生成 `device_id` 与 `session_id`（localStorage 持久），后续每个请求带
  `X-Device-Id` / `X-Session-Id` 请求头。
- 后端按 `device_id` 惰性注册用户，id 形如「用户+XXXX」（随机且主键唯一，冲突重试）。
- LLM / RAG / mem0 / 会话记录 全部携带 `user_id` + `session_id`。
- 前端调 `newSession()` 开启新会话（服务端上下文从此重新累积）。

## 目录结构

```text
.
├── app/                    # FastAPI 后端（自包含 uv 项目）
│   ├── pyproject.toml      # 依赖清单（uv）
│   ├── uv.lock
│   ├── .python-version     # Python 3.12.10
│   ├── .env                # 环境变量（不入库）
│   ├── main.py             # 主应用（CORS + 路由挂载 + 启动建表）
│   ├── config.py           # 环境变量配置
│   ├── db.py               # SQLAlchemy：users/sessions/messages + 惰性注册
│   ├── deps.py             # FastAPI 依赖：X-Device-Id → 用户身份
│   ├── models.py           # Pydantic 模型
│   ├── data/news.json      # JSON 种子数据 + 抓取入库
│   ├── agents/             # Agent 体系（ask(question, user_id, session_id)）
│   ├── routers/            # news / agents / cron 接口
│   ├── services/           # feeds llm embedding rag memory summarizer rss_ingest
│   └── storage/            # JSON 存储
├── web/                    # Vue3 + Vite + TS 前端（独立 npm 项目）
├── src/                    # autogen 等实验脚本（独立于 app，依赖未随 uv 管理）
├── .fastapicloud/          # FastAPICloud 部署配置（可选，不参与本地开发）
└── README.md
```

## 本地开发

前置：Python 3.10+（[uv](https://docs.astral.sh/uv/)）、Node 18+；一个 **Neon** 项目和一个 **硅基流动** key。

```bash
# 1. 后端
cd app
cp .env.example .env   # 填 DEEPSEEK_API_KEY / DATABASE_URL / EMBEDDING_API_KEY
uv sync
uv run uvicorn app.main:app --reload --port 8000   # API 文档 http://127.0.0.1:8000/docs

# 2. 前端（另开终端）
cd web && npm install && npm run dev               # http://localhost:5173

# 3. 手动触发一次 RSS 抓取（也可点前端「抓取最新」按钮）
cd app && uv run python -m app.services.rss_ingest
```

> 所有 `/api/*` 业务接口要求 `X-Device-Id` 请求头（前端会自动带）；缺省会 400。

### 环境变量

`app/.env`（或部署平台的环境变量）：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 必需 | DeepSeek 密钥（摘要、热度分、Agent 问答） |
| `DATABASE_URL` | 必需 | Neon Postgres 连接串（含 pgvector；用户/会话/消息 + RAG + mem0） |
| `EMBEDDING_API_KEY` | 必需 | 硅基流动密钥（RAG 与 mem0 的向量化；DeepSeek 无 embedding 接口） |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 可选 | 默认硅基流动 + `BAAI/bge-m3` |
| `CORS_ORIGINS` | 可选 | 允许跨域前端地址，逗号分隔 |
| `CRON_SECRET` | 可选 | `/api/cron/ingest` 鉴权 |
| `INGEST_PER_FEED` / `INGEST_MAX_ITEMS` / `SUMMARIZE_CONCURRENCY` | 可选 | 抓取/摘要参数 |

## 数据源配置

集中在 [app/services/feeds.py](app/services/feeds.py) 的 `DIRECT_FEEDS`：
少数派 / 36氪 / 虎嗅 / IT之家 / cnBeta / FT中文网 / 澎湃 / BBC中文 等原生 RSS 源。
抓取**按源容错**，新增数据源只需加一条。

## 记忆与 RAG

- 抓取入库时同步把新闻向量化写入 pgvector（`news_embeddings`，BGE-M3 1024 维）。
- 问 Agent 时上下文 = **会话历史 + mem0 用户记忆 + RAG 相关新闻 + 热点 top-N**。
- RAG 首次检索若向量库为空会自动对当前新闻补建索引。
- mem0 记忆按 `user_id` 隔离，跨会话累积用户关注点。

## 扩展新 Agent

1. `app/agents/` 下新建模块，继承 `Agent` 实现 `ask(question, *, user_id, session_id)`
2. 在 `app/agents/__init__.py` 的 `AGENTS` 字典注册
3. 前端 `web/src/agents.ts` 登记 label/icon

后端自动暴露 `GET /api/agents` 与 `POST /api/agents/{name}/ask`，前端 Tab 自动出现。

## API 一览

| 接口 | 说明 |
| --- | --- |
| `GET /api/news?category=&q=&page=&page_size=` | 新闻列表（分类/搜索/分页，按热度降序） |
| `GET /api/news/categories` | 分类及计数 |
| `GET /api/agents` | Agent 列表（含可用性） |
| `POST /api/agents/{name}/ask` | 向 Agent 提问（带 `X-Session-Id` 即多轮） |
| `POST /api/cron/ingest` | 手动触发抓取（配置 `CRON_SECRET` 可加鉴权） |

> 除 `/api/cron/ingest` 外，业务接口均要求请求头 `X-Device-Id`；`/api/agents/*` 可选 `X-Session-Id`。

## 部署（FastAPICloud + 云端数据库）

- **数据库**：[Neon](https://neon.tech) 建 Postgres 项目（默认支持 pgvector），
  把连接串作为 `DATABASE_URL` 配进后端平台环境变量。
- **embedding**：[硅基流动](https://siliconflow.cn) 申请 key，配 `EMBEDDING_API_KEY`。
- **后端**：FastAPICloud 部署，平台环境变量配 `DEEPSEEK_API_KEY` / `DATABASE_URL` /
  `EMBEDDING_API_KEY`（存储全在云端，无本地文件依赖）。
- **前端**：静态托管，生产域名在 `web/.env.production` 配
  `VITE_API_BASE_URL=https://后端域名`；后端 `CORS_ORIGINS` 需包含前端生产域名。
