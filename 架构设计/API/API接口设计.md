# API 接口设计

> **Base URL**: `http://localhost:8000/api/v1` | **路由文件**: `src/api/chat_routes.py`, `swarm_routes.py` | **最后更新**: 2026-05

---

## 一、聊天接口

### `POST /api/v1/chat` — 发送对话消息

**Request**:
```json
{
  "task_id": "session_1715692800000",
  "message": "什么是马氏体相变？",
  "deep_mode": false,
  "document_id": "abc123"
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 会话 ID，前端生成或复用 |
| `message` | string | 是 | 用户消息文本 |
| `deep_mode` | boolean | 否(默认false) | 深度模式：启用 HyDE 增强检索 + qwen-max+thinking |
| `document_id` | string | 否 | 关联文档 ID；为 null 时全库检索 |

**Response**: `202 Accepted`
```json
{"status": "received", "message": "对话已提交，Agent 正在检索与思考...", "mode": "knowledge_base"}
```
结果通过 SSE `/api/v1/notebook/stream` 异步推流。若 `document_id` 无效返回 `403 Forbidden`。

---

### `GET /api/v1/chat/sessions` — 列出对话会话

扫描 Redis 键 `xiaoye:chat:*:history`，返回：
```json
{
  "sessions": [
    {"task_id": "session_...", "message_count": 5, "preview": "什么是马氏体相变？", "last_user_msg": "什么是马氏体相变？"}
  ],
  "total": 3
}
```

### `DELETE /api/v1/chat/sessions/{task_id}` — 删除会话

删除 Redis 中的 `xiaoye:chat:{task_id}:history` 和 `xiaoye:chat:{task_id}` 键。

---

## 二、Fork 子代理接口

### `POST /api/v1/fork_agent` — 启动 Fork 子代理

**Request**:
```json
{
  "taskId": "task_abc123xyz",
  "documentId": "abc123",
  "type": "deep_research",
  "bbox": { "x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.6, "pageNumber": 3 }
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `taskId` | string | 是 | 唯一任务 ID |
| `documentId` | string | 是 | 目标 PDF 文档 ID |
| `type` | string | 是 | `"analyze_region"` 或 `"deep_research"` |
| `bbox` | object | 是 | 归一化坐标 (0-1) + 页码 |

**Response**: `200 OK`
```json
{"status": "ok", "message": "Fork deployed to background."}
```

---

## 三、SSE 流接口

### `GET /api/v1/notebook/stream` — SSE 事件流

**实现**: `sse_starlette.EventSourceResponse`，订阅 Redis PubSub 频道 `xiaoye_sse`，循环 `pubsub.get_message(timeout=1.0)` 转发到前端。客户端断开时自动取消订阅。详见[SSE事件规范](./SSE事件规范.md)。

---

## 四、文档管理接口

### `POST /api/v1/upload_pdf` — 上传 PDF

**Content-Type**: `multipart/form-data`，字段 `file: File`

**Response**:
```json
{"status": "success", "documentId": "abc123", "message": "File processed"}
```
或 `{"status": "exists", "documentId": "abc123", "message": "File already exists"}`

### `GET /api/v1/documents` — 文档列表

```json
{
  "documents": [
    {"id": "abc123", "filename": "paper.pdf", "status": "indexed", "created_at": "2026-05-01T..."}
  ]
}
```

### `GET /api/v1/documents/{id}/pdf` — PDF 下载/查看

返回 PDF 二进制流 (`application/pdf`)，由前端 `PdfViewer` 通过 `react-pdf` 渲染。

---

## 五、知识图谱接口

### `GET /api/v1/graph/*` — 图谱查询（调试端点）

通过 Neo4j 查询实体关系，返回图结构 JSON，供 `KnowledgeGraphViewer` 前端可视化使用。

---

## 六、AskUser 反询问接口

### `POST /api/v1/ask_user/reply` — 回答 Agent 反询问

```json
{"ask_id": "ask_uuid", "task_id": "session_123", "reply": "我想看淬火工艺对晶粒尺寸的影响"}
```
Agent 在缺乏关键信息时通过 SSE `ask_user` 事件向用户发问，用户回复后此接口将回复注入 Agent 继续执行。

---

## 七、静态图片服务

### `GET /api/images/{filename}` — 裁剪图片

FastAPI `StaticFiles` 挂载 `data/cropped_images/` 目录。Fork 子代理裁剪的 PDF 选区图片通过此端点服务给前端渲染。

---

## 八、Deep Mode 传递路径

```
前端 deepMode state
  → handleUserChat(message, deepMode=true)
  → POST /api/v1/chat {deep_mode: true}
  → background_chat_worker()
  → dispatch_chat_worker(deep_mode=True)
    → task_description 中包含 "深度模式已激活：启动高级知识图谱增强检索(HyDE)"
  → run_worker_pipeline(payload, task_id)
    → create_worker_graph(deep_mode=True)
      → model="qwen-max", thinking={"type":"auto","budget":32000}
```

**关键点**: `ChatRequest.deep_mode` 在三层（路由 → Worker → Graph）中逐级透传，最终影响模型选择和 System Prompt 中的工具加载指令。
