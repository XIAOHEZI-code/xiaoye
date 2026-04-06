# M1: RAG Schema 富媒体溯源升级

> 📌 冲刺周期：预计 2-3 个工作日
> 📌 前置依赖：CLAUDE.md 已就绪 ✅ | DEVELOPMENT_PROTOCOL.md 已就绪 ✅

## 🎯 本阶段目标 (一句话)

将现有的检索返回体从**纯文本 Chunk**  升级为带有 **(PDF_ID, 页码, Bounding Box, 图片 URI)** 的富媒体溯源结构，使前端未来能够实现"点击结果 → 跳到 PDF 原文"的精准定位体验。

## 📋 任务列表

### 1.1 数据入库层改造 (Pipeline / Marker-PDF)

- [x] 1.1.1 调研现有 `src/pipeline/` 中 Marker-PDF 输出的字段结构 ✅ 关键发现：`out_metadata` 被完全丢弃，是最大切入口
- [x] 1.1.2 设计新的 `ChunkDocument` 数据结构 ✅ 已创建 `src/models/chunk_document.py`
- [ ] 1.1.3 修改 Marker 解析脚本，确保输出包含上述全字段并写入 Elasticsearch

### 1.2 检索层改造 (Retrieval / ES)

- [x] 1.2.1 更新 Elasticsearch Index Mapping ✅ 增加 6 个富媒体字段 + 新建 `index_chunk_documents()` 方法
- [ ] 1.2.2 修改 `src/retrieval/semantic_search.py` 中的检索函数，使返回结果为 `List[ChunkDocument]` 而非 `List[str]`
- [ ] 1.2.3 确保 RRF (Reciprocal Rank Fusion) 混合检索的合并逻辑兼容新结构

### 1.3 Agent 消费层适配 (Agent / Graph)

- [ ] 1.3.1 修改 `src/agent/tools.py` 中的检索工具，使其接收和传递 `ChunkDocument` 结构
- [ ] 1.3.2 修改 `src/agent/graph.py` 中 Worker 节点的 context 拼装逻辑，使 LLM 在引用时带上来源标注（如 `[来源: xxx.pdf, p.12]`）

### 1.4 测试与验证

- [ ] 1.4.1 编写 `tests/test_chunk_document.py`：验证 ChunkDocument 的序列化/反序列化
- [ ] 1.4.2 编写 `tests/test_rag_schema.py`：用 3 篇测试 PDF 端到端验证新 Schema 的入库-检索-输出完整链路
- [ ] 1.4.3 手动验证：发一条自然语言查询，确认返回的 JSON 中包含正确的页码和 bbox

## 🚫 本阶段的边界 (不要越界)

- ❌ 不要动前端代码（M4 阶段的事）
- ❌ 不要修改 `swarm_coordinator.py` 的调度逻辑（M2 阶段的事）
- ❌ 不要引入 Celery / BackgroundTasks 等异步队列（M2 阶段的事）
- ❌ 不要新增 Python 依赖，除非在本文件此处显式声明：
  - （暂无）

## ✅ 完成标准 (Definition of Done)

1. 全部复选框 `[x]` 打勾
2. `pytest tests/test_chunk_document.py tests/test_rag_schema.py` 全部通过
3. 在终端运行一次手动查询，返回的 JSON 结果中包含 `page_number` 和 `source_pdf_id`
4. 更新 `work_log/WORKLOG.md` 追加本阶段总结

## 🔗 参考资源

- 架构蓝图：`work_log/human_ai_workspace_design.md` → M1 章节
- 项目禁令：`CLAUDE.md` → 第二节"绝对禁令"
- Claude Code 源码参考：如果遇到 Agent 架构设计问题，优先查阅 `claude-code-sourcemap/restored-src/src/tools/AgentTool/README.md`
