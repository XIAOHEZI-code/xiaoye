# 🌟 Xiaoye Agent 研发交接指南 (Handover Prompt for Assistant)

> **给下一位 AI 助手的最高行动准则**：
> 欢迎加入 Xiaoye 冶金 AI 平台的研发！请务必仔细阅读本提示词背景。本项目刚刚经历过一次底层大动脉级别的手术，**一切核心开发理念严格对标并吸收自 Anthropic 的 Claude Code 商业产品源码**。在对本项目进行任何修改前，请务必先领会我们从 Claude Code 中汲取的"异步解耦"、"环境探测"和"记忆压缩"思想！不要试图将本平台拉回早期传统的、串行的巨石阵（Monolithic）LangGraph 老套路中！

---

## 🏗️ 一、 当前工业级架构状态 (Architecture Design)
Xiaoye 是一个专门针对【冶金工程开发人员】的高并发、强容灾的多智能体协作平台。它目前基于以下四大核心设计哲学运行：

1. **沉浸式双核人机工位 (Human-AI Collaborative Workspace)**: 彻底抛弃传统的大语言模型"你问我答"阻塞流。架构设计上要求实现"左屏阅读检索源（富媒体及 PDF 区），右屏协同编辑（并发 Notebook 区）"。
2. **极简分形与剥离隔离 (Fork Subagent / Swarm Blackboard)**: 我们废弃了 LangGraph 的全局内存大回环以及无限递归造子代理的行为。采用单主脑（Coordinator）下发独立分支到黑板的模式；学习 Claude 的 `Fork` 机制：当人在前台进行阅读时，可以通过挂载纯后台全静默（`shouldAvoidPermissionPrompts`）的只读子 Agent 算力去解析特定块，并将结果通过 `FileEditTool` 工具无痛写回右侧面板。
3. **环境启发式技能装填 (Heuristic Skill Loading)**: 系统通过物理探针动态加载专用沙盒工具，如 `SQL_Agent_Tool` 或前端组件。并且遵循极端的上下文节流斩断法（例如只读的 Explore 子进程会被剥夺长篇 `claudeMd` 指南加载，节省巨幅开销）。
4. **硬盘态外挂记忆闭环 (Disk-Memory RAG)**: 不死磕短效的会话 History，转而使用 `agentMemory.ts` 同款的硬盘多作用域（Global/Project/Local）长程 Markdown 记忆存储法，以低计算成本实现终身学习闭环。

---

## 📂 二、 核心关键文件导航 (Key Files to Review)
在着手新需求之前，请务必查看以下重构后的核心组件了解执行逻辑：

### 后端核心
* `src/agent/swarm_coordinator.py`：**"大脑"**。异步调度中心，负责通过大模型拆解子任务写入黑板并休眠唤醒。
* `src/agent/task_board.py`：**"黑板"**。目前是基于本地 Json 实现的独立协程通信媒介，内置了 `depends_on` 的树状约束机制。
* `src/agent/graph.py`：**"手脚"**。已被降维，是一个纯粹负责执行底层 `tools` 流水线的纯劳工进程，不允许其继续招募下级。
* `src/core/memory_engine.py`：**"海马体"** (M4 新增)。三作用域硬盘态记忆引擎（global/project/session），实现 Prompt Preload 和对话后自动持久化。
* `src/core/swarm_workers/chat_worker.py`：**对话 Worker**。三模式自动切换（VLM/RAG/通用），集成记忆预加载(Step 0)、写操作安全阀门(Step 2a)、多来源歧义消解(Step 2c)、记忆持久化(Step 6)。
* `src/core/swarm_workers/fork_worker.py`：**Fork Worker**。PDF bbox 裁切 → VLM 视觉分析 → SSE 流式推送。
* `src/api/askuser_routes.py`：**主动求问 API** (M4 新增)。提供 `trigger_ask_user()` / `wait_for_user_reply()` 异步中断机制。

### 前端核心
* `frontend/src/App.tsx`：三栏布局 + SSE 监听 + AskUser 事件处理。
* `frontend/src/components/Notebook.tsx`：气泡化对话界面 + 思维链面板 + 流式打字光标 (M4 升级)。
* `frontend/src/components/PdfViewer.tsx`：PDF 渲染 + 右键 bbox 圈选 → ForkTask。
* `frontend/src/components/AskUserModal.tsx`：AI 主动求问弹窗 (M4 新增)，支持 confirm/choice/text 三种模式。
* `frontend/src/components/Sidebar.tsx`：知识库文档列表 + PDF 上传 + pending 状态自动轮询 (M4 升级)。

### 配置与文档
* `.xiaoye_memory/`：长程盘态记忆挂载目录（首次启动自动创建 global.md）。
* `work_log/TODO_M4_MEMORY_ASKUSER.md`：M4 任务清单（全部完成 ✅）。

---

## 🚀 三、 下行敏捷开发方向与发力点 (Future Development Pipeline)

### 已完成里程碑
* **M1 — RAG Schema 富媒体化** ✅：检索链输出附带 `source_bbox` 坐标的结构体。
* **M2 — 沉浸式前端搭建** ✅：Vite/React/TS 暗黑毛玻璃三栏布局。
* **M3 — 异步级联分发** ✅：FastAPI BackgroundTasks + SSE + Redis PubSub 全链路打通。
* **M4 — 主动求问 + 记忆引擎** ✅：AskUser UI + .xiaoye_memory/ + 气泡化对话 + 状态轮询。
* **M5 — 四管线架构重构与 GraphRAG 入库与可视化** ✅：实现四管线解耦。IngestionPipeline 实现原生管线编排（抽取三元组串联写入 Neo4j）。同时，在前端利用 `react-force-graph-2d` 实现了全景知识图谱的动态可视化界面，并打通了 `/api/v1/graph` 接口。

### M6 冲刺目标（待启动）
1. **物理化学 Code Sandbox 计算仪**：挂载安全的 Python 沙盒，Agent 可编写并执行物化计算代码，沙盒跑完后再拼回主面板。
2. **多用户会话隔离**：引入用户认证，实现文档/记忆/对话的多租户隔离。
3. **生产部署流水线**：Docker Compose 完整编排（含 ES 健康检查）+ Nginx 反向代理 + HTTPS。

---

## ⚠️ 重要注意事项
1. **Elasticsearch 目前未运行**：`docker compose ps` 显示 ES 容器未启动。RAG 检索需要 ES 才能工作，否则会自动降级为通用模式。启动命令：`docker compose up -d elasticsearch`。
2. **五条硬性禁令**：详见 `CLAUDE.md`，任何修改前必须先阅读。
3. **开发协议**：详见 `DEVELOPMENT_PROTOCOL.md`，每个新阶段必须先创建 TODO 文件。

---
