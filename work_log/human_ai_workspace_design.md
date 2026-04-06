# 小冶 (Xiaoye) 智能协同空间架构设计方案 (V2.0 完整演进版)

## 🎯 核心场景愿景与倒推分析

基于真实科研场景倒推，系统旨在解决四大痛点：

### 1. 泛读检索与降维发现 (Agent-to-SQL)
- **痛点**：用户想要寻找历史上的“带特定特征的数值模拟图像”，传统系统给不出。
- **架构支持**：引入 Router Agent 分流 SQL（查询时序和实验参数等结构化元数据）与 Vector（查询段落语义）。借助 **Marker-PDF** 解析时的深层清洗，返回结果不仅是文本，必须是带 **(PDF_ID, 页码, Bounding Box)** 的富媒体坐标，实现前端精准跳转追踪。

### 2. 深读推演与多体并行 (Forking & 沉浸式伴读)
- **痛点**：推导公式或分析局部段落时去查资料，主阅读流会被打断。
- **架构支持**：摒弃传统对话流，采用 **“左书右板 (Split-Screen Workspace)”**。左侧渲染连贯文档；鼠标框选高难内容后，前端发送异步指令调用后台 `Fork-Agent` 模块。子 Agent 在后台沙盒算完后，通过 `FileEditTool` 回冲（Push）到右偏 Markdown 共享笔记本。

### 3. 多模态破壁与疑点弹窗 (Vision & Ask-User Interactive)
- **痛点**：热力图谱或金相图片分析超出主语言模型能力，或者碰上数据歧义。
- **架构支持**：由主调度分发给悬挂了 Vision 模型（如 Qwen-VL）的只读子 Agent。当遇到不确定分类时，调用核心通讯层的 `AskUserQuestion`，以侧边栏浮浮窗 (Side-by-side Preview UI) 抛给人类决定，人类不点，分支任务挂起（Suspend），不阻断主窗口。

### 4. 长程记忆与项目结网 (Project Memory RAG)
- **痛点**：研究做了一个月，AI 其实全忘了昨天你们聊了啥。
- **架构支持**：废弃全部塞进 `History Message List` 的暴发户作法，采用 **扁平化文件态记忆**。人类与机器在右侧共享版写出的结论，自动落在 `.xiaoye_memory/xxx.md`。每次新开对话，前置预加载器会将其通过系统提示词下发，形成物理外脑。

---

## 🔬 可行性与技术鸿沟分析 (针对现有小冶底座)

目前系统底层情况（已知）：我们已经重构搭建了 LangGraph 为基础的 AgentSQL 网状流程，具备 RAGFlow 和 Marker-PDF 的入库能力，并加入了 Redis 恢复架构与 MCP 沙盒概念。

| 模块能力要求 | 现有底座支撑度 (Feasibility) | 技术鸿沟与改造难点 (Gap Analysis) |
| :--- | :--- | :--- |
| **富媒体查源响应** | 高。Elasticsearch 与 Marker 已经打通语义提取。 | 目前可能仅支持返回 Text Chunk。需扩写 ES Document 结构，绑定图像 URI（比如 S3 地址）并在最终生成返回体中输出带跳链的 JSON 卡片。 |
| **Fork 后台无阻断异步流** | 低/中。目前的 LangGraph 核心倾向于轮次同步（流式也是同步）。 | 致命难点：必须剥离主对话的 WebSocket 占用。要引入真正的后台分流器（如基于 FastAPI BackgroundTasks 或 Celery/Redis Queue）来下发子代理，彻底切断前台长连接的阻塞。 |
| **右侧协同笔记区写入** | 中。AI 使用 Tool 调用生成内容已是强项。 | UI 侧需搭建类 Jupyter/Notion 的长串编辑器。后端协议需改版：把原先吐 `AssistantMessage` 纯文本，改为吐出带有 `FileEditTool(action=append)` 的增量补丁，前端拦截这些补丁后渲染在右屏。 |
| **人机交互 Ask-User 落点** | 低。当前逻辑是 `Plan and Execute` 直接到底。 | 需要让 Agent 的工具池具备 `Suspend` (人类等待) 能力，涉及到基于 Redis 的会话挂起恢复，这极其挑战现有的 LangGraph Checkpoint 持久化机制。 |

---

## 🌊 瀑布式开发工作规划 (Waterfall Roadmap)

由于工程庞大，分为前端（人机交互舱）和后端（分布式逻辑脑）齐头并进，整体分为四个冲刺点 (M1-M4)：

### M1 - Backend RAG & RAGFlow Schema 升级改造
**目标**：将单一的文档检索拓展成支持（文、图、表）可跳转的元数据库。
- [ ] 后端目录 `rag_pipeline/schema/` 重构：为入库结构体增加 `source_bbox`, `image_uri`, `page_node` 特征。
- [ ] AgentSQL 节点改造：让 Retriever Node 吐出的不仅是 `context` 字符串，而是带有 Source Map 的富文本数组结构。

### M2 - Frontend UI / Workspace 搭建 (左书右板)
**目标**：实现沉浸式的协作体验面板界面。
- [ ] 新建前端工作区 `frontend/workspace_ui/` 模块。
- [ ] 实现 PDF 渲染层与高亮圈选器（左屏），绑定右键菜单抛出自定义 `ForkTaskEvent` 钩子。
- [ ] 实现协同编辑器（右屏），支持 Markdown 实时热渲染和流式补丁注入。

### M3 - Swarm Forking 架构引擎移植 (核心战役)
**目标**：打通长连接切分，借鉴 Claude 的 Fork 隔离思想。
- [ ] 新建后端包 `core/swarm_workers/`，实现 `forkSubagent` 模块：剥离主控上下文，精简 Prompt。
- [ ] Async Task 剥离：确保前台主会话 WebSocket 不被阻塞。子 Agent 使用独立的生命周期钩子往 Redis 队列扔出 `[FileEditTool]` 等待前端合并。

### M4 - 弹窗互动与物理记忆整合
**目标**：引入 `AskUser` 和基于操作系统的 `Agent_Memory.md`。
- [ ] 新建通信协议包 `core/interactive_tools/`，挂载原生的 UI 对讲机工具库（AskUserTool）。
- [ ] 在系统启动主引擎 `main.py` 之前，编写外挂读取逻辑，动态加载项目 `.xiaoye_memory/` 库形成系统级 Prompt Preloader。
