# 安心保（AnXinBao）

保险商城 + AI 智能顾问平台。提供在售保险产品展示与投保、基于 RAG 的流式保险问答（安安顾问）、保障方案推荐与确认、保单中心、理赔报案，以及保险条款/费率表知识库的解析入库与混合检索。

## 功能特性

- 🛒 **产品商城**：医疗险 / 重疾险 / 意外险 / 寿险分类浏览与产品卡片
- 🤖 **AI 智能顾问**：基于 LangGraph 的保险顾问 Agent（route 问题分类 → 三路并行检索 → ChatDeepSeek 流式生成），检索增强（产品库匹配 + 条款语义检索 + 费率表精确行算费），Postgres Checkpointer 保存会话状态，回答附带参考来源卡片
- 📋 **保障方案**：多产品推荐触发方案确认（interrupt），用户确认后保存，支持更换被保人
- 📄 **保单与理赔**：保单列表/详情/保障权益，理赔报案与状态流转
- 📚 **知识库（RAG）**：条款/费率表 PDF → MinerU 解析 → 切块入库 → bge 向量化 → Milvus 混合检索，并以 LangChain BaseRetriever 封装供 Agent 消费
- 🔐 **用户体系**：用户名密码登录（bcrypt）、个人资料管理、会话历史

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 · TypeScript · Vite 6 · Ant Design 5 |
| 后端 | Python 3.14 · FastAPI · SQLAlchemy 2 (async) · structlog |
| Agent 框架 | LangChain 1.x · LangGraph 1.x（StateGraph + AsyncPostgresSaver Checkpointer） |
| LLM | DeepSeek（`langchain-deepseek` ChatDeepSeek，SSE 流式） |
| 向量 | BAAI/bge-small-zh-v1.5（本地 CPU）· Milvus 3 |
| 存储 | PostgreSQL 16（asyncpg 业务库 + psycopg LangGraph checkpoint） |
| 部署 | Docker Compose · Nginx |

## 目录结构

```
安心保/
├── backend/                 # FastAPI 智能体服务
│   ├── app/
│   │   ├── main.py          # 入口（路由注册、lifespan、异常处理）
│   │   ├── core/            # config / exceptions / logging / agent_runtime（LangGraph 运行时）
│   │   ├── common/          # database / milvus / deps / utils / models
│   │   └── modules/         # user·products·policy·claim·insurance_plan·conversation·chat·knowledge
│   │       └── chat/        # agent.py（LangGraph 图）· rag.py（BaseRetriever 封装）· service / retrieval / router
│   ├── scripts/             # parse_kb / sync_milvus / 测试脚本（test_chat_sse、test_rate_consult 等）
│   ├── data/knowledge/      # 条款与费率表解析产物（JSON）
│   └── pyproject.toml       # uv 依赖
├── frontend/                # React SPA（详见 frontend/README.md）
├── deploy/                  # docker-compose 基础设施与数据库初始化 SQL
└── docs/项目设计文档.md      # 完整设计文档
```

## 快速开始

### 1. 启动基础设施（PostgreSQL + Milvus）

```bash
cd deploy
docker compose up -d
```

PostgreSQL 首次启动会自动执行 `postgres/init/` 下的建表与种子数据脚本；Attu 向量库管理界面位于 http://localhost:3000 。

### 2. 启动后端

```bash
cd backend
uv sync
# 配置 .env（必填 DEEPSEEK_API_KEY，其余见下）
uv run python -m app.main        # 默认 http://127.0.0.1:8001
```

关键环境变量（`backend/.env`）：

```ini
APP_NAME=安心保智能体服务
APP_PORT=8001
DB_HOST=localhost
DB_NAME=insurance
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
CHAT_AGENT_ENABLED=true          # false 时回退直连 LLM 旧路径
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
MILVUS_URI=http://127.0.0.1:19530
```

健康检查：`GET /health`；接口文档：`GET /docs`。启动时 LangGraph 运行时自动创建 checkpoint 表（`checkpoints` 等 4 张，psycopg 连接池）。

### 3. 初始化知识库（可选，问答需要条款/费率检索时执行）

解析产物 JSON 已随仓库提供（`backend/data/knowledge/`），直接入库即可：

```bash
cd backend
uv run python scripts/parse_kb.py parse                      # 仅当有 PDF 源文件时重新解析
curl -X POST http://127.0.0.1:8001/api/v1/knowledge/ingest   # JSON → 切块入库（幂等）
uv run python scripts/sync_milvus.py                         # 切块 → bge 向量 → Milvus
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173，/api 自动代理到后端 8001
```

## 测试

后端启动后（默认 8001），在 `backend/` 目录执行（需 `PYTHONPATH=.`）：

```bash
uv run python scripts/test_chat_sse.py       # SSE 契约端到端回归（流式/引用/方案确认/越权）
uv run python scripts/test_rate_consult.py   # 费率表精确行命中与算费回归
uv run python scripts/test_hybrid_search.py  # 知识库混合检索回归
uv run python scripts/test_knowledge.py      # 知识库模块 e2e
```

## API 概览

| 模块 | 端点 |
|---|---|
| 认证/用户 | `POST /api/v1/auth/login` · `GET/PATCH /api/v1/users/me` |
| 产品 | `GET /api/v1/products` |
| 智能问答 | `POST /api/v1/chat`（SSE）· `GET /api/v1/chat-threads/{id}/messages` · `POST /api/v1/chat-threads/{id}/chat`（SSE） |
| 会话 | `POST/GET /api/v1/chat-threads` · `PATCH/DELETE /api/v1/chat-threads/{id}` |
| 保障方案 | `GET /api/v1/insurance-plans/{id}` · `PATCH /api/v1/insurance-plans/{id}/items/{item_id}/insured` |
| 保单 | `GET /api/v1/policies[/{id}[/benefits]]` |
| 理赔 | `GET/POST /api/v1/claims` · `GET /api/v1/claims/{id}` · `PATCH /api/v1/claims/{id}/status` |
| 知识库 | `GET /api/v1/knowledge/documents[/{id}/chunks]` · `GET /search` · `POST /ingest` |

> 除登录外，接口需携带 `Authorization: Bearer <access_token>` 请求头（登录响应中返回的 JWT 访问令牌）。

## 部署

- 前端：`frontend/Dockerfile` 构建 Nginx 静态站点，`/api` 反代后端。
- 后端：`uvicorn app.main:app`，置于 Nginx 之后（SSE 已禁用缓冲）。
- 基础设施：`deploy/docker-compose.yml`（postgres / etcd / minio / milvus / attu）。

## 文档

- [项目设计文档](docs/项目设计文档.md)：架构、模块、数据模型、RAG 流程与设计取舍
- [前端说明](frontend/README.md)
