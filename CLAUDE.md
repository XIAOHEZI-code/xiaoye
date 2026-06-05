# Xiaoye 冶金 AI 平台 — 项目指引手册 (CLAUDE.md)
> **v0.2.0** | 2026-06-05 | 桌面端融合与测试优化版 — Claude Code 哲学推理管线 + Fork VLM 双模式 + 深度模式切换 | [GitHub](https://github.com/XIAOHEZI-code/xiaoye)

> **致所有参与本项目的 AI 助手**：请在每次动手写代码之前，阅读并理解本手册的全部约束。
> 本手册等效于你的"企业入职培训手册"。你在本项目中获批的、被禁止的行为，全部列在下方。

---

## 一、技术栈锁定 (Tech Stack — DO NOT DEVIATE)

| 层级 | 技术选型 | 版本约束 / 路径说明 |
| :--- | :--- | :--- |
| 语言 | Python | 3.12.x (Prefix-based conda 环境于 `./env_xiaoye/`) |
| Agent 框架 | LangGraph + LangChain | `langgraph>=0.2` |
| 向量数据库 | Elasticsearch (BM25 + Dense) | 8.x (Docker 容器映射 9200) |
| 关系数据库 | PostgreSQL | 15+ (Docker 容器映射 5432) |
| 缓存/队列 | Redis | 7.x (Docker 容器映射 6379) |
| 图数据库 | Neo4j | 5.x (Docker 容器映射 7474/7687) |
| PDF 解析 | Marker-PDF | latest |
| 前端 | React + TypeScript + Vite + Electron | 桌面端打包架构 |
| 容器化 | Docker Compose | 见 `docker-compose.yml` |

## 二、绝对禁令 (Hard Rules — NEVER BREAK)

1. **禁止回退串行巨石 LangGraph**：不许把 `graph.py` 恢复成一个包含规划、执行、反思的大循环。它只能是一个纯执行者（Worker）。规划权只属于 `swarm_coordinator.py`。
2. **禁止子 Agent 招募子 Agent**：参考 Claude Code 的 `forkSubagent.ts` 设计，任何被分发的 Worker 进程绝对不允许再调用 `AgentTool` 去创建新的子代理。违者直接 raise Error。
3. **禁止在 System Prompt 中塞入全部工具描述**：工具的挂载必须经过 `src/tooling/loader.py` 的环境探测与 `ToolRegistry` 的延迟注册。严禁在系统提示词中塞入硬编码的工具 Schema。
4. **禁止信赖纯内存 History**：长程知识必须外挂到 `.xiaoye_memory/` 目录下的 Markdown 文件中。不要试图通过不断追加对话的消息列表来让 Agent "记住"长程上下文。
5. **禁止直接 print 输出结果**：Agent 的产出物必须通过结构化的 Tool 调用写入文件或数据库，前端通过拉取这些结构化产出物来展示。

## 三、目录结构约定 (Project Layout)

```
xiaoye/
├── CLAUDE.md                    ← 你正在读的这个文件（项目大总管）
├── main.py                      ← 启动入口
├── requirements.txt             ← Python 依赖清单
├── pytest.ini                   ← 测试金字塔标记注册与配置
├── .env                         ← 环境变量配置文件
├── src/
│   ├── tooling/                 ← 工具管理管线
│   │   ├── definitions.py       ← 工具原子实现定义
│   │   ├── registry.py          ← 工具延迟注册表
│   │   └── loader.py            ← 环境探测式工具装填
│   ├── reasoning/               ← Agent 推理大脑
│   │   ├── graph.py             ← LangGraph ReAct 决策网络
│   │   └── state.py             ← 智能体状态定义
│   ├── delivery/                ← 任务分发与传输
│   │   ├── chat_worker.py       ← 对话任务 Worker 驱动
│   │   ├── fork_worker.py       ← 圈选 Fork 异步任务 Worker 驱动
│   │   └── sse_channel.py       ← 基于 Redis Pub/Sub 的 SSE 事件推送流
│   ├── ingestion/               ← 数据入库解析流水线
│   │   ├── pdf_parser.py        ← Marker PDF 解析与页码映射切块
│   │   ├── pipeline.py          ← 异步入库核心调度管线
│   │   └── image_analyzer.py    ← Qwen-VL 图片视觉指标分类提取
│   ├── retrieval/               ← 混合检索与知识增强
│   │   ├── semantic_search.py   ← ES 语义及 BM25 混合搜索
│   │   ├── rrf_search.py        ← Reciprocal Rank Fusion 融合算法
│   │   ├── graph_search.py      ← Neo4j 知识图谱三元组检索
│   │   └── hyde_searcher.py     ← 事实锚定型假设文档生成（HyDE）
│   ├── tools/                   ← 平台内置独立工具
│   │   ├── sandbox.py           ← 基于 ZMQ 的有状态 Jupyter 代码执行沙盒
│   │   └── pdf_cropper.py       ← PDF 坐标高清裁切工具
│   ├── db/                      ← 数据库模型与会话管理
│   └── api/                     ← FastAPI 路由层
├── frontend/                    ← 前端客户端与桌面外壳
│   ├── electron/                ← Electron 桌面主进程与生命周期控制
│   ├── src/                     ← React + TS 渲染进程页面与交互
│   └── package.json             ← 前端及桌面依赖清单
├── .xiaoye_memory/              ← 长程盘态记忆挂载目录
├── work_log/                    ← 研发日志、系统运行日志与环境说明
│   └── ENVIRONMENT.md           ← 本地开发与服务运维启动指南
├── 软著/                        ← 软著申报材料
│   └── paper/
│       └── 软件说明书.md        ← 系统用户说明书
└── tests/                       ← 测试金字塔集
    ├── small/                   ← 纯 Mock 单元测试
    ├── medium/                  ← 涉及 ES/Redis/Neo4j/Postgres 的集成测试
    └── large/                   ← 涉及真实大模型调用的 E2E 测试
```

## 四、代码风格 (Code Style)

- 函数命名：`snake_case`，类命名：`PascalCase`
- 所有新函数必须带 docstring（至少一行描述 + 参数说明）
- 异步函数使用 `async def`，禁止在异步上下文中使用阻塞 IO
- 新增文件顶部必须写一行注释说明该模块的单一职责
- commit message 格式：`feat(module): 简述` / `fix(module): 简述` / `refactor(module): 简述`

## 五、测试与运行常用命令 (Commands)

### 1. 运行测试
*   **激活 Conda 环境**：`source /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye/bin/activate` 或 `conda activate /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye`
*   **运行单元测试（Mock）**：`./env_xiaoye/bin/python -m pytest -m small`
*   **运行集成测试（需 Docker）**：`./env_xiaoye/bin/python -m pytest -m integration`

### 2. 本地服务管理
*   **启动 Docker 依赖**：`docker compose up -d db redis elasticsearch neo4j`
*   **检查 Docker 状态**：`docker compose ps`
*   **本地启动 FastAPI 后端（开发模式）**：`./env_xiaoye/bin/python main.py`
*   **后台挂起 FastAPI 后端（独立会话）**：
    ```bash
    setsid -f env_xiaoye/bin/python -c "
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=False)
    " > backend.log 2>&1
    ```

### 3. 前端与 Electron 桌面端
*   **安装前端依赖**：`cd frontend && npm install`
*   **启动前端开发服务（HMR）**：`cd frontend && npm run dev`
*   **编译前端产物（供后端 Serve）**：`cd frontend && npm run build`
