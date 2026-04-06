---
description: 环境管理标准操作流程 — Miniconda + Docker + Git
---

# 环境管理 Workflow

// turbo-all

## 1. Conda 环境操作

### 创建环境
```bash
conda env create -f environment.yml
```

### 激活环境
```bash
conda activate xiaoye
```

### 更新环境（依赖变更后）
```bash
conda env update -f environment.yml --prune
```

### 导出当前环境快照
```bash
conda env export --no-builds > environment.lock.yml
```

### 删除环境（重建时）
```bash
conda env remove -n xiaoye
```

## 2. Docker 操作

### 构建镜像
```bash
docker compose build
```

### 启动服务（开发模式，前台）
```bash
docker compose up
```

### 启动服务（后台）
```bash
docker compose up -d
```

### 查看日志
```bash
docker compose logs -f app
```

### 停止并清理
```bash
docker compose down
```

### 完全重建（代码或依赖变更后）
```bash
docker compose down && docker compose build --no-cache && docker compose up -d
```

## 3. Git 操作规范

### 提交规范 (Conventional Commits)
```
feat: 新功能
fix: Bug 修复
refactor: 重构（不改变功能）
docs: 文档变更
test: 测试相关
chore: 构建/工具变更
```

### 典型工作流
```bash
# 创建功能分支
git checkout -b feat/feature-name

# 提交变更
git add -A
git commit -m "feat: describe the change"

# 合并回主分支
git checkout main
git merge feat/feature-name
git branch -d feat/feature-name
```

## 4. 规则

- **严禁全局安装 Python 包**，所有依赖通过 `conda` 或 `pip`（在 conda 环境内）管理
- **严禁直接修改 `main` 分支**，所有变更通过功能分支 + merge
- Docker 用于**部署和集成测试**，Conda 用于**日常开发**
