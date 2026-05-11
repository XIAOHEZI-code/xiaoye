"""
P4: Delivery Pipeline — 交互管线

职责：对话管理 → 记忆 → SSE 推送 → 前端渲染
独立性：通过接口消费 Reasoning 结果，管理会话生命周期
依赖：P3 Reasoning 的推理接口

模块清单：
  - chat_worker.py:   主对话 Worker (迁移自 src/core/swarm_workers/chat_worker.py)
  - memory.py:        三作用域记忆引擎 (迁移自 src/core/memory_engine.py)
  - sse_channel.py:   SSE 推送统一抽象层
  - session.py:       会话管理器 (多用户隔离基础)
"""
