# Xiaoye 冶金 AI 平台 — 项目指引手册 (CLAUDE.md)
> **v0.1.0** | 2026-05-20 | 首个纯净发行版 — Claude Code 哲学推理管线 + Fork VLM 双模式 + 深度模式切换 | [GitHub](https://github.com/XIAOHEZI-code/xiaoye)

> **致所有参与本项目的 AI 助手**：请在每次动手写代码之前，阅读并理解本手册的全部约束。
> 本手册等效于你的"企业入职培训手册"。你在本项目中获批的、被禁止的行为，全部列在下方。

---

## 一、技术栈锁定 (Tech Stack — DO NOT DEVIATE)

| 层级 | 技术选型 | 版本约束 |
| :--- | :--- | :--- |
| 语言 | Python | 3.11 / 3.12 |
| Agent 框架 | LangGraph + LangChain | `langgraph>=0.2` |
| 向量数据库 | Elasticsearch (BM25 + Dense) | 8.x |
| 关系数据库 | PostgreSQL | 15+ |
| 缓存/队列 | Redis | 7.x |
| PDF 解析 | Marker-PDF | latest |
| 前端 (未来) | React + TipTap/ProseMirror | TBD |
| 容器化 | Docker Compose | 见 `docker-compose.yml` |

## 二、绝对禁令 (Hard Rules — NEVER BREAK)

1. **禁止回退串行巨石 LangGraph**：不许把 `graph.py` 恢复成一个包含规划、执行、反思的大循环。它只能是一个纯执行者（Worker）。规划权只属于 `swarm_coordinator.py`。
2. **禁止子 Agent 招募子 Agent**：参考 Claude Code 的 `forkSubagent.ts` 设计，任何被分发的 Worker 进程绝对不允许再调用 `AgentTool` 去创建新的子代理。违者直接 raise Error。
3. **禁止在 System Prompt 中塞入全部工具描述**：工具的挂载必须经过 `skill_loader.py` 的环境探测。如果当前目录下没有 `.csv` 文件，则不许向 LLM 暴露 SQL 工具。
4. **禁止信赖纯内存 History**：长程知识必须外挂到 `.xiaoye_memory/` 目录下的 Markdown 文件中。不要试图通过不断追加对话的消息列表来让 Agent "记住"长程上下文。
5. **禁止直接 print 输出结果**：Agent 的产出物必须通过结构化的 Tool 调用写入文件或数据库，前端通过拉取这些结构化产出物来展示。

## 三、目录结构约定 (Project Layout)

```
xiaoye/
├── CLAUDE.md                    ← 你正在读的这个文件（项目大总管）
├── main.py                      ← 启动入口
├── src/
│   ├── agent/
│   │   ├── swarm_coordinator.py ← 唯一的"大脑"，负责任务拆解
│   │   ├── task_board.py        ← 黑板通信介质
│   │   ├── graph.py             ← 纯执行流水线（Worker）
│   │   ├── skill_loader.py      ← 环境探测式工具装填
│   │   └── ultraplan.py         ← Ultraplan 规划引擎
│   ├── core/                    ← 未来放 swarm_workers/ 和 interactive_tools/
│   ├── retrieval/               ← 检索链（向量+BM25 RRF 混合）
│   ├── pipeline/                ← 数据入库管线（Marker-PDF 解析）
│   ├── tools/                   ← Agent 可调用的原子工具集
│   ├── db/                      ← 数据库模型与迁移
│   └── api/                     ← FastAPI 路由层
├── .xiaoye_memory/              ← 长程盘态记忆挂载目录
├── work_log/                    ← 研发日志与架构蓝图
│   ├── HANDOVER_PROMPT.md       ← AI 交接指南
│   └── human_ai_workspace_design.md ← M1-M4 架构升级路线
└── tests/                       ← 单元与集成测试
```

## 四、代码风格 (Code Style)

- 函数命名：`snake_case`，类命名：`PascalCase`
- 所有新函数必须带 docstring（至少一行描述 + 参数说明）
- 异步函数使用 `async def`，禁止在异步上下文中使用阻塞 IO
- 新增文件顶部必须写一行注释说明该模块的单一职责
- commit message 格式：`feat(module): 简述` / `fix(module): 简述` / `refactor(module): 简述`
