# M6 紧急架构重构计划 (Delivery -> Reasoning 闭环接入)

> **创建日期**: 2026-05-11
> **目标**: 将目前被架空的 `src/reasoning/graph.py` (LangGraph ReAct 循环) 正式接入实际的主线对话 (`chat_worker.py`) 中，赋予大模型自主使用工具、自我评估和检索质量控制的能力。

## 🎯 Phase 1: Reasoning 图的流式改造 (SSE 注入)
目标：把“黑盒”图变成透明的进度条，使前端能在 Agent 思考时实时看到进度。

- [ ] **重写 `run_worker_pipeline` 签名**：允许传入 `task_id`，以便绑定 SSE 推送管道。
- [ ] **接入 `astream_events` (LangGraph)**：监听 `on_chat_model_stream` 和 `on_tool_start`/`on_tool_end` 事件。
- [ ] **SSE 事件编解码器映射**：
  - 工具调用 -> `patch: "\n> 🛠️ [系统思考中] 正在调用工具..."`
  - LLM Token 生成 -> `patch: chunk.content`
- [ ] **Evaluator 反馈外显**：如果 Evaluator 驳回了当前的检索结果，通过 SSE 提示前端用户 `patch: "\n> 🤔 数据不充分，正在尝试更换策略重新检索..."`。

## 🎯 Phase 2: Delivery 核心管线的切换
目标：删除临时硬编码逻辑，实现真正的智能体派发。

- [ ] **清空旧逻辑**：移除 `chat_worker.py` 中写死的 `semantic_search` 工具调用和 `ChatOpenAI` 原生调用流。
- [ ] **Prompt 整合转移**：把刚才在 `chat_worker.py` 中写好的优秀提示词（如“直接给出具体数据、渲染图注 Markdown”）平滑转移到 `reasoning/graph.py` 中的 `ResearcherNode`。
- [ ] **参数透传**：确保原有的 `memory_context`（硬盘长程记忆）和对话历史被组装成连贯的 `SystemMessage` 传入 Graph 的初始 State 中。
- [ ] **异常与超时兜底**：LangGraph 循环极其消耗资源，加入防止死循环的最终阀门保障，即使 Evaluator 连续判定失败，在达到最大重试次数时也必须给出总结回答。

## 🎯 Phase 3: 架构精简与废弃代码清理
目标：清理历史包袱，减轻后续 M6 开发（可视化图表、多租户等）的认知负担。

- [ ] **停用与隔离遗留调试文件**：建立 `_archive/` 文件夹，将根目录下废弃的测试脚本（如 `test_e2e_pipeline.py`, `scratch_test.py` 等）移入归档。
- [ ] **评估废弃子模块**：检查并可能废弃 `src/reasoning/coordinator.py` 和 `src/reasoning/planner.py`，让单体 `WorkerGraph` 成为唯一的思考中枢，以减少不必要的 Swarm 调度复杂度。
- [ ] **提交 Git Baseline**：跑通全链路测试，生成稳定的代码基线。

---
*注：此计划将优先于原定的前端可视化沙盒进度执行，因为它是整个平台真正具备“科研助理”智能的神经中枢。*
