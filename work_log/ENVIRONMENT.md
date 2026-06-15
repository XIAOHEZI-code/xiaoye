# Xiaoye 项目环境启动指南

> 最后更新: 2026-06-04 | 适用于本地开发/调试场景

---

## 一、Conda 环境（测试环境）

- **名称**: xiaoye
- **位置**: `/home/xiaohezi/Desktop/project/xiaoye/env_xiaoye/`
- **Python**: 3.12.13
- **创建方式**: `conda create -p ./env_xiaoye python=3.12 -y`
- **注意**: 此环境为 prefix-based 安装，不在 `~/.conda/environments.txt` 中，不能用 `conda activate xiaoye` 激活

### 激活方式

```bash
# 方式一：直接激活路径
conda activate /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye

# 方式二：source 激活脚本
source /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye/bin/activate
```

### 已安装的核心依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| fastapi | 0.135.3 | Web 框架 |
| uvicorn | 0.44.0 | ASGI 服务器 |
| langchain | 1.2.15 | LLM 框架 |
| langgraph | 1.1.6 | Agent 图编排 |
| langchain-openai | 1.1.9 | OpenAI 集成 |
| sqlalchemy | 2.0.49 | ORM |
| elasticsearch | 8.19.3 | 搜索引擎 |
| redis | 7.4.0 | 缓存/队列客户端 |
| celery | 5.6.3 | 异步任务队列 |
| psycopg2-binary | 2.9.11 | PostgreSQL 驱动 |
| asyncpg | 0.31.0 | 异步 PG 驱动 |
| neo4j | 6.1.0 | 图数据库客户端 |
| pydantic | 2.12.5 | 数据校验 |
| marker-pdf | 1.10.2 | PDF 解析 |
| torch | 2.11.0 | 深度学习 |
| transformers | 4.57.6 | HuggingFace 模型 |

---

## 二、Docker 基础服务

### 镜像状态

| 镜像 | 用途 | 状态 |
|------|------|------|
| `xiaoye-app:latest` (13.3 GB) | 后端应用 | ✅ 已构建 |
| `postgres:15-alpine` | 关系数据库 | ✅ 运行中 (5432) |
| `redis:7-alpine` | 缓存/队列 | ✅ 运行中 (6379) |
| `neo4j:5-community` | 图数据库 | ✅ 运行中 (7474/7687) |
| `elasticsearch:8.12.2` | 向量搜索 | ⚠️ 已退出 (需重启) |

### Docker Compose 管理

```bash
cd /home/xiaohezi/Desktop/project/xiaoye

# 启动所有基础服务 (postgres + redis + es + neo4j)
docker compose up -d db redis elasticsearch neo4j

# 启动 app 容器 (会同时启动所有依赖)
docker compose up -d app

# 查看运行状态
docker compose ps

# 停止所有服务
docker compose down

# 仅重启 elasticsearch
docker compose restart elasticsearch
```

### Docker 容器端口映射

| 服务 | 容器内端口 | 宿主机端口 |
|------|-----------|-----------|
| app (FastAPI) | 8000 | 8000 |
| PostgreSQL | 5432 | 5432 |
| Redis | 6379 | 6379 |
| Elasticsearch | 9200 | 9200 |
| Neo4j HTTP | 7474 | 7474 |
| Neo4j Bolt | 7687 | 7687 |

---

## 三、后端启动 (FastAPI)

### Conda 本地开发模式 (推荐调试)

```bash
# 1. 激活环境
conda activate /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye

# 2. 入项目目录
cd /home/xiaohezi/Desktop/project/xiaoye

# 3. 启动后端 (生产模式，脱离终端)
setsid -f env_xiaoye/bin/python -c "
import uvicorn
uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=False)
" > backend.log 2>&1

# 或者开发模式 (hot reload, 但需保持终端打开)
# python main.py
# => uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

访问:
- API 文档: http://localhost:8000/docs
- 前端页面: http://localhost:8000/ (需先 `cd frontend && npm run build`)
- 裁剪图片: http://localhost:8000/api/images/

> ⚠️ 注意: 不要用 `&` 或 `nohup` 后台运行，终端关闭后子进程会被杀死。使用 `setsid -f` 创建独立会话以确保持久运行。

### Docker 模式

```bash
cd /home/xiaohezi/Desktop/project/xiaoye
docker compose up -d --build app
```

---

## 四、前端启动 (React + Vite)

### 开发模式 (Vite HMR, 热更新)

```bash
cd /home/xiaohezi/Desktop/project/xiaoye/frontend
npm run dev
# => Vite dev server, 默认 http://localhost:5173
```

Vite 配置了代理: 所有 `/api` 请求自动转发到 `http://localhost:8000`

### 生产构建

```bash
cd /home/xiaohezi/Desktop/project/xiaoye/frontend
npm run build
# => 生成 dist/ 目录，由后端 FastAPI 直接 serve
```

构建后启动后端即可访问: http://localhost:8000/

---

## 五、检查清单

启动前确认:

- [ ] Conda 环境已激活 (`which python` 应指向 `env_xiaoye/bin/python`)
- [ ] PostgreSQL 容器运行中 (`docker ps | grep postgres`)
- [ ] Redis 容器运行中 (`docker ps | grep redis`)
- [ ] Elasticsearch 容器运行中 (`docker ps | grep elasticsearch`)
- [ ] Neo4j 容器运行中 (`docker ps | grep neo4j`)
- [ ] `.env` 文件配置正确 (数据库连接信息)

快速检查命令:
```bash
# 检查 Docker 容器
docker compose -f /home/xiaohezi/Desktop/project/xiaoye/docker-compose.yml ps

# 检查 conda 环境
ls /home/xiaohezi/Desktop/project/xiaoye/env_xiaoye/bin/python

# 检查前端依赖
ls /home/xiaohezi/Desktop/project/xiaoye/frontend/node_modules/.package-lock.json 2>/dev/null && echo "前端依赖已安装" || echo "需要 npm install"
```
