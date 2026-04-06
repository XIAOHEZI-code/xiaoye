# 🌟 Xiaoye Agent 研发交接指南 (Handover Prompt for Assistant)

> **给下一位 AI 助手的最高行动准则**：
> 欢迎加入 Xiaoye 冶金 AI 平台的研发！请务必仔细阅读本提示词背景。本项目刚刚经历过一次底层大动脉级别的手术，**一切核心开发理念严格对标并吸收自 Anthropic 的 Claude Code 商业产品源码**。在对本项目进行任何修改前，请务必先领会我们从 Claude Code 中汲取的“异步解耦”、“环境探测”和“记忆压缩”思想！不要试图将本平台拉回早期传统的、串行的巨石阵（Monolithic）LangGraph 老套路中！

---

## 🏗️ 一、 当前工业级架构状态 (Architecture Design)
Xiaoye 是一个专门针对【冶金工程开发人员】的高并发、强容灾的多智能体协作平台。它目前基于以下四大核心设计哲学运行：

1. **沉浸式双核人机工位 (Human-AI Collaborative Workspace)**: 彻底抛弃传统的大语言模型“你问我答”阻塞流。架构设计上要求实现“左屏阅读检索源（富媒体及 PDF 区），右屏协同编辑（并发 Notebook 区）”。
2. **极简分形与剥离隔离 (Fork Subagent / Swarm Blackboard)**: 我们废弃了 LangGraph 的全局内存大回环以及无限递归造子代理的行为。采用单主脑（Coordinator）下发独立分支到黑板的模式；学习 Claude 的 `Fork` 机制：当人在前台进行阅读时，可以通过挂载纯后台全静默（`shouldAvoidPermissionPrompts`）的只读子 Agent 算力去解析特定块，并将结果通过 `FileEditTool` 工具无痛写回右侧面板。
3. **环境启发式技能装填 (Heuristic Skill Loading)**: 系统通过物理探针动态加载专用沙盒工具，如 `SQL_Agent_Tool` 或前端组件。并且遵循极端的上下文节流斩断法（例如只读的 Explore 子进程会被剥夺长篇 `claudeMd` 指南加载，节省巨幅开销）。
4. **硬盘态外挂记忆闭环 (Disk-Memory RAG)**: 不死磕短效的会话 History，转而使用 `agentMemory.ts` 同款的硬盘多作用域（Global/Project/Local）长程 Markdown 记忆存储法，以低计算成本实现终身学习闭环。

---

## 📂 二、 核心关键文件导航 (Key Files to Review)
在着手新需求之前，请务必查看以下重构后的核心组件了解执行逻辑：

* `xiaoye/src/agent/swarm_coordinator.py`：**“大脑”**。异步调度中心，负责通过大模型拆解子任务写入黑板并休眠唤醒。
* `xiaoye/src/agent/task_board.py`：**“黑板”**。目前是基于本地 Json 实现的独立协程通信媒介，内置了 `depends_on` 的树状约束机制。
* `xiaoye/src/agent/graph.py`：**“手脚”**。已被降维，是一个纯粹负责执行底层 `tools` 流水线的纯劳工进程，不允许其继续招募下级。
* `xiaoye/xiaoye_memory/`：**“海马体”**。作为长程记忆读写目录，它将成为 Agent 在新开会话时做 Prompt Preload（系统提示词初始化）的最可靠外挂。
* `xiaoye/work_log/human_ai_workspace_design.md`：**“工程蓝图”**。保留了详尽的 M1 - M4 架构升级迭代路径。当你拿不准如何设计并发逻辑和通讯时，**请优先回忆并查找我们从 Claude Code 源码库中挖掘的设计手段！**

---

## 🚀 三、 下行敏捷开发方向与发力点 (Future Development Pipeline)
你的研发方向由传统的后端中枢延伸出了真正的工业软件级协同功能：

### 1. 业务与协同开拓 (Business & Interaction Logic)
* **Agent-to-SQL + 高精确富媒体溯源 (M1 冲刺)**：不仅要进行文本检索，检索链（Retriever Node）必须输出附带 `source_bbox` 坐标的结构体，在左侧富媒体屏上达到所见即所得。
* **主动求问决断网 (AskUser Interaction Hook)**：打破 AI 不定性幻觉，如果 Agent 在沙盒解析中遇阻，强制使用类似 `AskUserQuestionTool` 的前端钩子，以 Side-by-side（双边对比）的气泡弹窗把多模型方案交给人类去选择后再向后流转。

### 2. 生产级工程壁垒 (Engineering Resiliency)
* **从阻塞向彻底的异步分发转换 (M2/M3 冲刺)**：`task_board.py` 与 LangGraph Checkpoint 需要进行最硬核的手术。把传统阻塞 WebSocket 的跑数流程拆入 BackgroundTasks / Redis Celery 队列，保证前端的 UI 面板极简顺滑。
* **物理化学 Code Sandbox 计算仪**：大语言模型面对“吉布斯自由能”推演必跪。必须给 Agent 挂接安全的 Python沙盒，通过 `FileEditTool` 工具流式输出计算代码，沙盒跑完后再拼回主面板。

---

> 👋 **写给你的最终提示框**：
> 当用户抛出新需求时，请回忆一下你在 Claude Code 中学到的经验（Idle, Context Trim, Muted Tool Loading）。以最为优雅且节省算力的方式将解法植入进 Xiaoye 中。现在，请和开发人员打个招呼并询问下一个需要实施落地的任务是什么吧！
