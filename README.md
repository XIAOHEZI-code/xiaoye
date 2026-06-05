# 🔬 小冶 (Xiaoye) — 冶金智慧文献 AI 平台

> **AI 驱动的冶金文献深度解析与知识推理系统**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1-green.svg)](https://www.langchain.com/langgraph)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![Electron](https://img.shields.io/badge/Electron-35-47848F.svg)](https://www.electronjs.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

小冶是一个面向冶金科研场景的 **AI Agent 文献分析平台**，结合大语言模型（Qwen-Max/Turbo）、知识图谱（Neo4j）与语义检索（Elasticsearch），为研究人员提供从 PDF 解析 → 知识抽取 → 智能问答 → 文献综述全链路的 AI 辅助能力。

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                    🖥️ Electron 桌面端                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  PDF 阅读器  │  │  AI 对话面板  │  │  知识库 & Fork   │   │
│  │  (选区分析)  │  │  (ReAct Agent)│  │  (图谱/文献管理) │   │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │               │                    │              │
├─────────┼───────────────┼────────────────────┼──────────────┤
│         ▼               ▼                    ▼              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              FastAPI 后端 (Port 8000)                 │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │   │
│  │  │ PDF 入库 │  │ HyDE 检索 │  │  ReAct Agent     │  │   │
│  │  │ Pipeline │  │ 增强管线  │  │  推理循环        │  │   │
│  │  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │   │
│  └───────┼──────────────┼─────────────────┼────────────┘   │
│          │              │                  │               │
├──────────┼──────────────┼──────────────────┼───────────────┤
│          ▼              ▼                  ▼               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │PostgreSQL│  │  Neo4j   │  │   Redis  │  │ Elastics.│  │
│  │  15      │  │  5       │  │  7       │  │  8.12    │  │
│  │ 文档/会话│  │ 知识图谱 │  │ SSE/队列 │  │ 语义索引 │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                🐳 Docker Compose 容器编排                  │
└──────────────────────────────────────────────────────────┘
```

---

## 📑 核心功能详解

### 5.1 基于 Marker 的 PDF 切片与富媒体索引建立

我们采用 **Marker-PDF** 作为底层解析引擎，构建了多层次的文档入库管线：

- **Markdown 语义切块**：将 PDF 解析后的 Markdown 按段落语义边界进行智能切分（`chunk_size=1000`，`chunk_overlap=200`），保留表格与公式结构
- **三策略页码映射**（`_build_page_map`）：
  1. **图片锚点匹配**：解析 `![](_page_N_xxx)` 标注，定位图片所在页码
  2. **目录标题匹配**：对齐 Marker 输出的 TOC 条目与正文段落
  3. **前向继承传播**：未标注段落自动继承上一已知页码
- **图表 VLM 视觉分析**（Fork Pipeline）：利用视觉大模型对论文中的金相图、工艺流程图进行语义理解，生成自然语言描述
- **Elasticsearch 混合索引**：同时建立 BM25 稀疏索引（关键词精确匹配）与 Dense 向量索引（语义相似检索），通过 RRF 算法融合排序

```
PDF → Marker 解析 → Markdown → 切块 + 页码映射 + 图表提取
                                    ↓
                            ES 索引 (BM25 + Dense)
```

### 5.2 基于 Neo4j 图数据库的 HyDE 检索增强

在传统 RAG 基础上，我们引入了 **KG-Anchored HyDE (Hypothetical Document Embeddings)** 增强检索：

- **三元组知识图谱抽取**（`Neo4jGraphExtractor`）：
  - 第一遍 LLM 抽取（Extraction）：从文献文本中提取 (Subject, Relation, Object) 三元组
  - 第二遍 LLM 规范化（Normalization）：统一实体名称、消除指代歧义
  - 存入 Neo4j 图数据库，形成冶金领域知识网络

- **HyDE 增强检索管线**（`HyDESearcher`）：
  1. **实体提取**：从用户问题中识别冶金实体（材料、工艺、设备）
  2. **图谱锚定**：在 Neo4j 中查找实体的直接关系（1-hop），获取机制描述
  3. **假设性文档生成**：LLM 基于图谱上下文生成假想的"标准答案"文档
  4. **语义检索融合**：将原问题 + HyDE 文档拼接，在 ES 中进行混合检索

```
用户问题 → 实体提取 → 图谱查询(Neo4j) → HyDE 文档生成 → ES 语义检索 → 答案合成
```

### 5.3 基于 ReAct 与 LangChain 的 Agent 设计

遵循 **Claude Code 工程哲学**（don't gold-plate，精简高效），我们设计了纯 Worker 模式的 ReAct 推理循环：

- **Worker ReAct 循环**：
  ```
  Researcher → ToolNode → Compactor → Evaluator → Synthesizer
       ↑                                              │
       └──────────── 步骤未满足，继续循环 ←──────────────┘
  ```
  - **Researcher**：分析当前状态，决定调用哪个工具
  - **ToolNode**：执行工具调用（语义搜索、图谱查询、沙盒计算）
  - **Compactor**：压缩工具输出（Jaccard 相似度去重、Token 预算控制）
  - **Synthesizer**：过滤 ToolMessage + tool_calls AIMessage，基于已收集资料生成最终答案

- **模型分层**：FAST 模式使用 `qwen-turbo`（快速响应），DEEP 模式使用 `qwen-max` + 32000 Token thinking budget（深度推理）
- **硬性约束**：最大 12 轮迭代，单轮工具输出上限 12K Token，防止死循环和 Token 击穿
- **禁止递归招募**：Worker 进程绝对不允许创建子 Agent，遵循 Claude Code `forkSubagent.ts` 设计原则

### 5.4 基于 Electron 的前端设计

我们采用 **Vite + React 19 + Electron 35** 三合一架构，构建了类 IDE 的专业桌面应用：

- **三栏布局**：PDF 阅读器（左）| AI 对话面板（中）| 知识库与 Fork 管理（右），支持拖拽调整宽度与折叠
- **无边框窗口**：自定义 TitleBar 组件，提供窗口最小化/最大化/关闭控制，适配 Windows/macOS/Linux
- **双模式路由**：浏览器环境通过 Vite 代理转发 API；Electron 环境直连 FastAPI 后端，消除代理开销
- **SSE 流式推送**：基于 Server-Sent Events 实现 Agent 推理过程的实时展示（思考链 + 检索进度 + Fork VLM 截图）
- **本地文件极速上传**（`upload_local_pdf`）：Electron 端通过 `shutil.copy` 直拷文件系统，**零 HTTP 协议开销**，比传统 FormData 上传快 5-10 倍
- **状态持久化**：布局、对话、文档选择等通过 localStorage 持久化，刷新不丢失

```
Vite Dev Server (:5173) ──→ React 前端
       │
       ├── /api/* ──(proxy)──→ FastAPI (:8000)
       │
       └── vite-plugin-electron ──→ Electron 桌面窗口
              ├── main.ts     (窗口管理 + IPC)
              └── preload.ts  (Node.js API 桥接)
```

### 5.5 基于 Docker 的容器化与沙盒设计

我们采用 **Docker Compose** 实现一键全栈部署，同时设计了多层环境隔离策略：

- **五服务编排**（`docker-compose.yml`）：
  | 服务 | 镜像 | 端口 | 用途 |
  |------|------|:---:|------|
  | `app` | 自构建 (3.2 GB) | 8000 | FastAPI 后端 |
  | `db` | postgres:15-alpine | 5432 | 文档元数据/会话存储 |
  | `redis` | redis:7-alpine | 6379 | SSE 消息队列/缓存 |
  | `elasticsearch` | elasticsearch:8.12.2 | 9200 | 向量 + BM25 语义索引 |
  | `neo4j` | neo4j:5-community | 7474/7687 | 知识图谱存储 |

- **三层环境隔离**：
  1. **Native OS**：宿主操作系统（文件系统直访）
  2. **Conda 环境**（`env_xiaoye/`）：Python 3.12 开发测试环境，所有依赖隔离
  3. **Docker 容器**：生产级运行时，数据库服务独立容器化

- **沙盒文件系统挂载**：
  - `data/cropped_images/`：Fork VLM 选区截图输出目录
  - `frontend/dist/`：生产构建前端静态文件，由 FastAPI 直接 serve

- **安全策略**：容器间通过 `xiaoye-network` 内部通信，仅暴露必要端口到宿主机；数据库密码通过 `.env` 环境变量注入，不硬编码

---

## 🚀 快速启动

### 环境要求

- Python 3.12 + Conda
- Node.js 25 + npm 11
- Docker & Docker Compose

### 1. 启动基础服务

```bash
docker compose up -d db redis elasticsearch neo4j
```

### 2. 启动后端 (FastAPI)

```bash
# 激活 conda 环境
conda activate /path/to/xiaoye/env_xiaoye

# 生产模式 (脱离终端)
setsid -f python -c "
import uvicorn
uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=False)
" > backend.log 2>&1

# 开发模式 (hot reload，需保持终端)
python main.py
```

访问 API 文档：http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend
npm install   # 首次运行
npm run dev   # Vite + Electron 同时启动
```

- **Web 访问**：http://localhost:5173
- **Electron 桌面窗口**：自动弹出（DISPLAY 环境变量需正确配置）

### 4. 运行测试

```bash
# Small 测试 (纯 Mock，无外部依赖)
pytest tests/small/ -v -m small

# Medium 测试 (需 Docker 服务运行)
pytest tests/medium/ -v -m medium

# Large E2E 测试 (消耗真实 LLM Token，默认跳过)
RUN_E2E=true pytest tests/large/ -v
```

---

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|:---|:---|:---|
| **Agent 框架** | LangGraph + LangChain | 1.1 / 1.2 |
| **LLM** | Qwen-Max / Qwen-Turbo | 通义千问 2.5 |
| **后端** | FastAPI + Uvicorn | 0.135 / 0.44 |
| **向量检索** | Elasticsearch (BM25 + Dense) | 8.12 |
| **图数据库** | Neo4j | 5 (Community) |
| **关系数据库** | PostgreSQL | 15 |
| **缓存/队列** | Redis + Celery | 7 / 5.6 |
| **PDF 解析** | Marker-PDF | 1.10 |
| **前端** | React + Vite | 19 / 8 |
| **桌面端** | Electron | 35 |
| **深度学习** | PyTorch + Transformers | 2.11 / 4.57 |
| **容器化** | Docker Compose | — |

---

## 📁 项目结构

```
xiaoye/
├── main.py                 ← FastAPI 启动入口
├── docker-compose.yml      ← 五服务编排
├── Dockerfile              ← App 镜像构建
├── requirements.txt        ← Python 依赖
├── .env.example            ← 环境变量模板
├── src/
│   ├── api/                ← FastAPI 路由层
│   ├── reasoning/          ← ReAct Agent 推理引擎
│   ├── retrieval/          ← HyDE 检索 + ES + Neo4j
│   ├── ingestion/          ← PDF 解析 + 三元组抽取
│   ├── delivery/           ← 消息队列 + 上下文构建
│   ├── core/               ← 配置与日志
│   ├── db/                 ← 数据库模型
│   └── models/             ← Pydantic 数据模型
├── frontend/
│   ├── src/                ← React 组件
│   ├── electron/           ← Electron 主进程
│   └── vite.config.ts      ← Vite + Electron 插件配置
├── tests/
│   ├── small/              ← 单元测试 (纯 Mock)
│   ├── medium/             ← 集成测试 (连接 Docker)
│   └── large/              ← E2E 测试 (真实 LLM)
└── eval/                   ← 基准测试与评估脚本
```

---

## 📄 许可证

MIT License © 2026 Xiaoye Team

---

<p align="center">
  <b>小冶</b> — 让 AI 成为你的冶金科研伙伴 🔥
</p>
