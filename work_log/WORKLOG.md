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

## 2026-04-14 M4-A 冲刺代码交付（工具链渐进式披露升级与工程热修复）

### 一、 架构目标达成 (ToolSearchTool 渐进式披露)

本次迭代彻底重构了工具暴露机制，解决了由 LLM 上下文衰减导致的“关键词无法匹配工具”问题，正式移植了 Claude Code 的 **ToolSearchTool（渐进式披露）** 设计模式。

#### 核心变更：
1. **`ToolSearchEngine` 倒排检索索引 (`src/agent/tool_search.py`)**
   - 实现内存级倒排索引和评分器，支持基于预定义 `search_hint` / `category` 的精确选取和模糊检索。
2. **具象化安全隔离 (`src/agent/tools.py`)**
   - 不再向 LangGraph 粗暴传递全量 Tool，所有工具现在都挂载了 `ToolMetadata` 并拥有 `should_defer=True` (延迟加载) 属性。大模型初始只能看见"文本检索"和"工具查询"。
3. **环境解耦 (`skill_loader.py`)**
   - 移除了所有老旧的硬编码字符串匹配（"计算", "文献"），不再越俎代庖去推测大模型需要什么工具，而是把拉取工具的主动权还给 Agent 本身。
4. **全量引擎适配 (`graph.py`)**
   - 对齐了 LangGraph `@tool` 绑定的边界条件：`ResearcherNode` (LLM 端) 虽然只被动态绑定基础工具链，但底层的 `ToolNode` (执行引擎端) 被正确赋予了 `ALL_TOOLS` 权限全集，严丝合缝消除了节点映射异常。

### 二、 工程可用性修复 (Hotfixes)

1. **API 模块断链修复**：排除了由 M1-M3 重构带来的调用遗留问题：
   - 彻底移除了废弃的 `create_metallurgy_agent` 路由僵尸调用，对接为现代化的 `create_worker_graph` 事件流。
   - 订正了 Marker-PDF 提取器在 debug 路由下的拼写错误（`split_markdown_into_chunk_documents`）。
2. **底层环境补齐**：使用了正确的虚拟环境 `env_xiaoye`，并且打补丁安装了 `jupyter_client` 与 `python-multipart` 依赖，确保 `uvicorn main:app` 后端网关一次性启动成功无报错。

## 下一步计划：M4-B 子冲刺前瞻 (用户决议流)
目前 Worker 基础设施均已贯通，接下来的 B 阶段我们可以向前端/安全层面倾斜，当前已准备好两条路径待命：
1. **M4-B1**: `Jupyter Sandbox` 物理沙盒隔离强化 (防范生成恶意破坏性探针脚本)
2. **M4-B2**: Human-in-the-Loop (`SuspendTask` 交互中断求问体系，处理复杂二义性任务时的上行确认过程)

---

## 2026-04-19 Fork 更新：LangGraph 1.x 兼容性修复

### 一、问题背景

LangGraph 1.x 与 LangChain `@tool` 装饰器存在 API 不兼容，导致：

```
TypeError: unhashable type: 'StructuredTool'
```

具体报错位置：
- `skill_loader.py:35` — `set(tools_to_load)` 无法哈希 StructuredTool
- `graph.py:121` — `ToolNode(ALL_TOOLS)` 工具绑定失败
- LLM API 调用时报错：`[] is too short - 'tools'`

### 二、修复方案（方案 C：StructuredTool 包装）

#### 2.1 核心修改文件

| 文件 | 改动内容 | 状态 |
|------|---------|------|
| `src/agent/tools.py` | `@tool` → `StructuredTool.from_function()` | ✅ |
| `src/agent/skill_loader.py` | 函数→工具映射修复 | ✅ |
| `src/api/debug_routes.py` | 错误处理改进 | ✅ |

#### 2.2 Pydantic 输入模型（tools.py 新增）

```python
class SearchTextInput(BaseModel):
    query: str = Field(description="Search query text")
    top_k: int = Field(default=3)

class GraphRelationsInput(BaseModel):
    entity: str = Field(description="Metallurgy entity name")

class ImpactPathInput(BaseModel):
    entity: str = Field(description="Entity to trace")

class PythonCodeInput(BaseModel):
    code: str = Field(description="Python code")

class SearchToolsInput(BaseModel):
    query: str = Field(description="Tool search query")
    max_results: int = Field(default=5)
```

#### 2.3 工具包装示例（tools.py）

```python
# 修改前（@tool 装饰器）
@tool
def search_metallurgy_text(query: str, top_k: int = 3) -> str:
    ...

# 修改后（StructuredTool）
def search_metallurgy_text(query: str, top_k: int = 3) -> str:
    ...

TEXT_TOOLS = [
    StructuredTool.from_function(
        func=search_metallurgy_text,
        name="search_metallurgy_text",
        description="Search for chunked texts...",
        args_schema=SearchTextInput
    )
]
```

#### 2.4 工具映射修复（skill_loader.py）

```python
def probe_environment(self, task_description: str):
    tools_to_load = get_tools_for_step(task_description)
    
    tool_map = {t.name: t for t in ALL_TOOLS}  # 建立 name→Tool 映射
    
    result = []
    for item in tools_to_load:
        if callable(item) and hasattr(item, '__name__'):
            for t in ALL_TOOLS:
                if t.func == item:  # 匹配函数
                    result.append(t)
        elif hasattr(item, 'name'):
            result.append(item)
    return result
```

### 三、验证结果

| 测试项 | 状态 | 说明 |
|-------|------|------|
| ToolNode 创建 | ✅ | 5个工具加载成功 |
| 工具加载 | ✅ | 2个核心工具 (search_metallurgy_text, search_available_tools) |
| upload_pdf | ✅ | 200 OK |
| fork_agent | ✅ | 200 OK |

### 四、分支与备份

- **工作分支**: `langgraph-fix`
- **备份文件**: `src/agent/tools.py.backup`
- **合并命令**: `git merge langgraph-fix`

### 五、后续建议

1. **长期**：添加完整的 LangGraph 流式测试
2. **长期**：ES 索引创建 + PDF 导入 pipeline
3. **依赖**：监控 LangChain/LangGraph 版本兼容性
