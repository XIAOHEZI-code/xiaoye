"""
P2: Tooling Pipeline — 工具管线

职责：工具注册 → 渐进式披露 → 执行 → 结果格式化
独立性：只依赖底层检索/沙盒实现，不依赖 Agent/Delivery
对外暴露：ToolRegistry 接口协议

模块清单：
  - registry.py:       ToolRegistry ABC + 默认实现
  - definitions.py:    全部原子工具定义 (迁移自 src/agent/tools.py)
  - search_engine.py:  渐进式工具搜索引擎 (迁移自 src/agent/tool_search.py)
  - loader.py:         环境探测式装填 (迁移自 src/agent/skill_loader.py)
"""
