# Xiaoye 冶金 AI 平台 — 工作日志

---

## 2026-04-02 Agent 架构审查与改进规划

### 一、当前能力盘点

Xiaoye Agent 基于 LangGraph 实现了 **Adaptive Self-RAG (Plan-and-Execute)** 框架，具备以下已落地能力：

| 能力模块 | 实现文件 | 状态 |
| --- | --- | --- |
| 结构化任务拆解 (Planner) | `src/agent/graph.py` | ✅ 已上线 |
| 反幻觉评估拦截 (Evaluator) | `src/agent/graph.py` | ✅ 已上线 |
| 语义 + BM25 混合检索 (RRF 融合) | `src/retrieval/semantic_search.py` | ✅ 已上线 |
| 知识图谱单跳/多跳因果追溯 | `src/retrieval/graph_search.py` | ✅ 已上线 |
| 冶金图表多模态 V2T 降维分析 | `src/pipeline/image_analyzer.py` | ✅ 已上线 |
| 上下文 Microcompact 防溢出 | `src/agent/graph.py` (compactor_node) | 🆕 本次新增 |
| 动态工具按需装载 | `src/agent/tools.py` (get_tools_for_step) | 🆕 本次新增 |
| Swarm TaskBoard 原型 | `src/agent/task_board.py` | 🆕 本次新增 |

### 二、本次已完成的架构升级（基于 Claude Code 源码调研反哺）

#### 2.1 Microcompact 上下文压缩拦截器

- **问题**：Researcher 调用的检索工具返回的大段文本原封不动带入后续节点，极易引发 Context Overflow。
- **方案**：在 `tools → evaluator` 的边上插入 `compactor_node`，对超过 3000 字符的 ToolMessage 自动截断并附加 Tombstone 标记。
- **源码位置**：`src/agent/graph.py` — `compactor_node()` 函数。

#### 2.2 动态技能树（按需 Tool Binding）

- **问题**：所有工具被硬编码一次性绑定到 LLM，随着工具增多 Prompt Token 成本剧增。
- **方案**：将 `AGENT_TOOLS` 拆分为 `TEXT_TOOLS` / `GRAPH_TOOLS`，通过 `get_tools_for_step()` 根据当前子任务的关键词启发式匹配，仅注入相关工具。
- **源码位置**：`src/agent/tools.py` — `TOOL_REGISTRY` + `get_tools_for_step()`。

#### 2.3 Swarm TaskBoard 原型

- **问题**：单体 `AgentState` 大字典传递，崩溃不可恢复，不支持并行检索。
- **方案**：创建文件系统级任务黑板 `TaskBoard`，Planner 发布任务，多个 Researcher 并行领取和提交结果。
- **源码位置**：`src/agent/task_board.py`。

### 三、规范化改进建议（待实施）

#### 3.1 Human-In-The-Loop 人类审查门阀

> **优先级：🔴 高**

当 Agent 即将执行高危操作（如生成 SQL 并执行到生产数据库）时，必须有一个 `permission_node` 中断流程，等待人类在前端点击"Approve"后才能继续。这是 Agent to SQL 上线的前置安全保障。

#### 3.2 流式状态回传（Streaming Events）

> **优先级：🟡 中**

利用 LangGraph 的 `.astream_events()` API，让前端能实时渲染出：  
*"Planner 正在思考规划" → "Researcher 正在翻阅文献图谱" → "Evaluator 检测发现不足正在回溯"*  
的实时呼吸灯/Loading 流水效果，增强用户的交互信心。

#### 3.3 MemorySaver 会话记忆守恒

> **优先级：🟡 中**

为 `StateGraph` 加载 LangChain 官方的 `SqliteSaver` 或 `AsyncRedisSaver`，实现 Checkpoint 持久化。系统重启后可恢复中断的会话，支持类似 Claude `--resume` 的断点续传。

### 四、面向冶金工程领域的功能扩展规划

> 以下四项功能专为冶金工程开发研究员设计，旨在弥补 LLM 在高等数学/数值计算领域的原生短板。

#### 4.1 🧮 Code Interpreter 科学计算沙盒

- **面向场景**：传质动力学（菲克扩散定律）、热流体计算、边界层传质通量。
- **设计思路**：内置一个受限 Python 沙盒 Tool。Agent 遇到计算类需求时，不去"背书"，而是自动生成含 Numpy/Scipy 的代码并在本地安全执行，返回**精确数值结果**。
- **示例交互**：
  > 🧑‍🔬 *"请帮我计算碳在 1000°C γ-Fe 固溶体中扩散 2 小时后的理论渗碳深度"*  
  > 🤖 Agent → 生成 Python 代码（使用 Fick 第二定律 + 误差函数） → 沙盒执行 → 返回 `渗碳深度 ≈ 1.23mm`

#### 4.2 🌡️ 热力学/相图对接计算模块

- **面向场景**：物理化学（吉布斯自由能）、相平衡状态预推、冶金热力学。
- **设计思路**：开发 `Thermodynamics_Calculator_Tool`，桥接开源 **PyCalphad**（TDB 热力学数据库）或通过内部 RPC 调用商用 Thermo-Calc / FactSage。
- **示例交互**：
  > 🧑‍🔬 *"304 不锈钢在 800°C 随着 C 含量增加，会析出什么相？"*  
  > 🤖 Agent → 调用 PyCalphad → 计算相平衡 → 返回 *"当 C > 0.05% 时开始析出 M23C6 碳化物相"*

#### 4.3 📊 实验数据智能清洗与可视化

- **面向场景**：冶金化学实验结果分析、光谱/能谱（EDS‑XRF）表格数据处理。
- **设计思路**：新增 `Data_Analysis_Tool`，用户上传 CSV/Excel 测试报告，Agent 利用 Pandas 进行异常去噪、相关性分析，并调用 Plotly/Matplotlib 自动生成可视化趋势图。
- **示例交互**：
  > 🧑‍🔬 *"这批渣系的碱度设定与最终脱磷率是否存在明显相关性？"*  
  > 🤖 Agent → 读取 CSV → Pandas 皮尔森相关分析 → 生成散点图 + 拟合线 → 返回 *"r = 0.87，强正相关"*

#### 4.4 🗄️ 高频物性参数 SQL Agent（Agent to SQL）

- **面向场景**：精确的合金成分配比查询、高温下黏度/比热容/导热率的数值提取。
- **设计思路**：将内部掌握的合金物性矩阵数据（如渣系参数、合金密度等）导入关系型数据库。Agent 将自然语言问题翻译为精确 SQL 查询，实现精准的定量数据获取。
- **示例交互**：
  > 🧑‍🔬 *"查一下 1600°C 碱度大于 1.2 的精炼渣系的理论黏度范围"*  
  > 🤖 Agent → 生成 `SELECT viscosity_range FROM slag_properties WHERE temp=1600 AND basicity > 1.2` → 返回表格

---

### 附录：技术栈参考

| 组件 | 当前方案 | 建议升级 |
| --- | --- | --- |
| LLM 主模型 | Qwen-Max | 保持 |
| 视觉模型 | Qwen-VL-Max | 保持 |
| 向量数据库 | Elasticsearch KNN | 保持 |
| 图框架 | LangGraph StateGraph | 保持，增加 Checkpoint |
| 计算沙盒 | ❌ 缺失 | 新增 Python Sandbox |
| 热力学引擎 | ❌ 缺失 | 新增 PyCalphad 桥接 |
| 数据分析 | ❌ 缺失 | 新增 Pandas Tool |
| SQL Agent | ❌ 缺失 | 新增 SQL Agent Tool |
| 会话持久化 | ❌ 缺失 | 新增 SqliteSaver |
| 权限审查 | ❌ 缺失 | 新增 Permission Node |
