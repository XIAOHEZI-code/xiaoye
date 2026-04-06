---
name: mdr-framework
description: |
  基于 Markdown 的高确定性重构框架 (Markdown-based Deterministic Refactoring Framework)。
  当需要进行以下操作时使用此技能：
  (1) 模块重构 (2) 性能优化 (3) 接口重新设计 (4) 遗留代码清理 (5) 架构升级。
  此框架通过结构化 Markdown 标签严格约束 AI 的行为边界，确保重构过程可控、可追溯、可回滚。
---

# MDR Framework — 基于 Markdown 的高确定性重构框架

## Overview

本技能定义了一套**结构化重构协议**，通过 Markdown 标签精确控制 AI 的输入解析和输出格式，确保大型项目重构的安全性和确定性。

核心原则：**明确边界 → 硬约束 → 契约驱动 → 可验证输出**

---

## Part 1: Input Protocol（用户输入协议）

用户发起重构任务时，**必须**按以下 Markdown 结构组织 prompt：

### `# [Core Objective]` — 核心目标

- 本轮任务的终极目标，AI 不得偏离
- 一句话描述要做什么，为什么做

### `## Context & Scope` — 上下文与边界

- **目标文件**：明确列出要修改的文件路径
- **调用方文件**：列出依赖这些文件的上下游模块
- **作用域声明**：明确说明"仅限于 X，不改变 Y"

### `## Constraints (DOs/DONTs)` — 硬约束

- `DO`：必须遵守的正向规则
- `DONT`：**硬限制器**——违反即判定为重构失败，AI 必须在输出前自检

### `## Dependencies` — 依赖声明（可选）

列出重构涉及的：
- 外部依赖（第三方库版本约束）
- 内部依赖（模块间调用关系）
- 数据依赖（数据库、缓存、消息队列）

### `## Data/Interface Contracts` — 数据/接口契约（可选）

使用 Markdown 表格定义接口契约：

```markdown
| 参数名 | 类型 | 约束 |
| :--- | :--- | :--- |
| user_id | UUID | 必填 |
| time_range | String | 可选，默认 '7d' |
```

### 附带原始代码片段

在 prompt 末尾附上需要重构的原始代码，使用对应语言的 fenced code block。

---

## Part 2: Output Protocol（AI 输出协议）

AI 的响应**必须**严格按以下结构输出，禁止对话式填充：

### `### Refactoring Strategy（重构策略）`

- 最多 3 个要点的 bullet list
- 解释架构层面的变更（如：解耦逻辑、更新状态管理、拆分职责）

### `### Impact Analysis（影响范围分析）`

Markdown 表格列出受影响的模块：

```markdown
| 受影响模块 | 影响类型 | 说明 |
| :--- | :--- | :--- |
| analytics_service.py | 调用方式变更 | 需更新函数签名 |
| test_user_stats.py | 测试用例 | 需补充新测试 |
```

如无影响，声明 "No external impact."

### `### Interface / Contract Changes（接口/契约变更）`

```markdown
| Before | After | Rationale |
| :--- | :--- | :--- |
| `get_stats(uid)` | `get_stats(uid, range='7d')` | 支持时间范围筛选 |
```

如无变更，声明 "No contract changes."

### `### Implementation（代码实现）`

- 使用对应语言标签的 fenced code block
- 复杂逻辑处必须有行内注释
- 如涉及多文件，按文件路径分节输出

### `### Rollback Plan（回滚方案）`

- 列出回滚步骤（如何撤销本次变更）
- 如有数据迁移，说明回滚数据的方法

### `### Validation Checklist（验证清单）`

分层列出验证项：

- **Unit Test**：函数级别的输入输出验证
- **Integration Test**：模块间交互验证
- **Regression Test**：确认未破坏现有功能的关键路径

---

## Part 3: Multi-File Refactoring Protocol（多文件重构协议）

当重构涉及 **3 个以上文件** 时，启用分阶段执行：

### Phase 定义

```markdown
## Execution Phases

### Phase 1: [描述] — 涉及文件: `file_a.py`, `file_b.py`
### Phase 2: [描述] — 涉及文件: `file_c.py`, `file_d.py`  
### Phase 3: [集成测试] — 验证 Phase 1 + 2 的交互
```

### 规则

1. 每个 Phase 独立输出完整的 Output Protocol
2. Phase 之间必须有用户确认节点
3. 后续 Phase 可以引用前序 Phase 的输出

---

## Best Practices

### DO
- 在重构前先确认 Context & Scope 的完整性
- 对每个 DONT 约束进行自检后再输出
- 多文件重构时使用分阶段协议
- 在 Impact Analysis 中列出所有受影响的测试文件

### DON'T
- 修改 Context & Scope 之外的任何文件
- 忽略 DONT 约束中的任何一条
- 在单次输出中处理超过 5 个文件的重构
- 省略 Rollback Plan（即使看似简单的变更）
