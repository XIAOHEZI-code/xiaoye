# 示例：优化数据库查询逻辑以降低响应延迟

以下是使用 MDR Framework 的完整 prompt 模板示例。

---

```markdown
# 优化数据库查询逻辑以降低响应延迟

## Context & Scope
- 目标文件：`/src/db/queries/user_stats.sql`
- 调用方文件：`/src/services/analytics_service.py`
- 仅限于优化查询语句和数据聚合方式，不改变现有的数据流向。

## Constraints (DOs/DONTs)
- DO: 使用索引友好的查询结构。
- DO: 在聚合查询中使用 `WHERE` 前置过滤而非 `HAVING` 后置过滤。
- DONT: 严禁修改现有的数据库表结构 (Schema)。
- DONT: 严禁在 Python 层进行全表遍历过滤。
- DONT: 严禁删除或修改现有的 API 返回字段。

## Dependencies
- 外部依赖：SQLAlchemy 2.0+, PostgreSQL 15
- 内部依赖：`analytics_service.py` 调用 `user_stats.sql` 的查询结果
- 数据依赖：`user_actions` 表，`user_profiles` 表

## Data/Interface Contracts
| 参数名 | 类型 | 约束 |
| :--- | :--- | :--- |
| user_id | UUID | 必填 |
| time_range | String | 可选，默认 '7d' |
| group_by | String | 可选，默认 'day' |

## 原始代码

\`\`\`sql
-- user_stats.sql
SELECT u.user_id, u.username, 
       COUNT(a.action_id) as total_actions,
       SUM(CASE WHEN a.action_type = 'purchase' THEN a.amount ELSE 0 END) as total_spent
FROM user_profiles u
LEFT JOIN user_actions a ON u.user_id = a.user_id
GROUP BY u.user_id, u.username
HAVING COUNT(a.action_id) > 0;
\`\`\`

\`\`\`python
# analytics_service.py
def get_user_stats(user_id: str, time_range: str = '7d'):
    raw = db.execute(load_sql('user_stats.sql'))
    # 全表加载后在 Python 层过滤
    filtered = [r for r in raw if r['user_id'] == user_id]
    return filtered[0] if filtered else None
\`\`\`
```

---

## 预期 AI 输出结构

AI 应按以下顺序输出：

1. **Refactoring Strategy** — 3 点策略说明
2. **Impact Analysis** — 受影响模块表格
3. **Interface / Contract Changes** — Before/After 对比表
4. **Implementation** — 重构后的代码
5. **Rollback Plan** — 回滚步骤
6. **Validation Checklist** — Unit / Integration / Regression 分层验证
