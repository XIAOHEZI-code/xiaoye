"""
P3: Reasoning Pipeline — 推理管线

职责：Coordinator → 规划 → Worker ReAct 循环 → 结果聚合
独立性：通过 ToolRegistry 接口消费工具，不直接 import 工具定义
依赖：P2 Tooling 的 ToolRegistry 接口

模块清单：
  - graph.py:        Worker ReAct 循环 (迁移自 src/agent/graph.py)
  - state.py:        AgentState 类型定义 (迁移自 src/agent/state.py)
  - coordinator.py:  Swarm 调度中心 (迁移自 src/agent/swarm_coordinator.py)
  - task_board.py:   Redis 黑板通信 (迁移自 src/agent/task_board.py)
  - planner.py:      UltraPlan 规划引擎 (迁移自 src/agent/ultraplan.py)
"""
