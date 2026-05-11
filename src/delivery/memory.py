"""
Memory Engine — 硬盘态三作用域长程记忆管理

遵循 HANDOVER_PROMPT.md 第 4 条设计哲学（Disk-Memory RAG）：
  不死磕短效的会话 History，转而使用硬盘多作用域 Markdown 记忆存储。

三个作用域：
  - global.md:           全局记忆（跨项目通用的冶金知识偏好、用户习惯）
  - project_{doc_id}.md: 项目级记忆（某篇文献的分析笔记、关键发现）
  - session_{task_id}.md: 会话级记忆（单次对话的上下文摘要）

职责：
  1. 新会话启动时自动读取相关记忆作为 System Prompt 的 preload 注入
  2. 对话结束/达到阈值时自动提取关键信息写入记忆文件
  3. 记忆文件可被用户直接编辑（透明的 Markdown 文件）
"""

import os
import re
from datetime import datetime
from typing import Optional

# 记忆目录
MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".xiaoye_memory")


def _ensure_memory_dir():
    """确保记忆目录存在"""
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _memory_path(scope: str, scope_id: Optional[str] = None) -> str:
    """
    根据作用域构建记忆文件路径。

    Args:
        scope:    'global' | 'project' | 'session'
        scope_id: 当 scope 为 project/session 时的唯一标识
    Returns:
        记忆文件的绝对路径
    """
    _ensure_memory_dir()
    if scope == "global":
        return os.path.join(MEMORY_DIR, "global.md")
    elif scope == "project" and scope_id:
        # 清理 scope_id 中的非法文件名字符
        safe_id = re.sub(r'[^\w\-]', '_', scope_id)
        return os.path.join(MEMORY_DIR, f"project_{safe_id}.md")
    elif scope == "session" and scope_id:
        safe_id = re.sub(r'[^\w\-]', '_', scope_id)
        return os.path.join(MEMORY_DIR, f"session_{safe_id}.md")
    else:
        raise ValueError(f"Invalid memory scope: scope={scope}, scope_id={scope_id}")


def read_memory(scope: str, scope_id: Optional[str] = None) -> str:
    """
    读取指定作用域的记忆内容。

    Args:
        scope:    'global' | 'project' | 'session'
        scope_id: 项目/会话的唯一 ID
    Returns:
        记忆文件的 Markdown 文本内容（文件不存在时返回空字符串）
    """
    path = _memory_path(scope, scope_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def write_memory(scope: str, content: str, scope_id: Optional[str] = None, append: bool = True):
    """
    写入记忆到指定作用域。

    Args:
        scope:    'global' | 'project' | 'session'
        content:  要写入的 Markdown 内容
        scope_id: 项目/会话的唯一 ID
        append:   True 则追加（默认），False 则覆盖
    """
    path = _memory_path(scope, scope_id)
    mode = "a" if append else "w"

    # 追加时自动加时间戳分隔
    if append and os.path.exists(path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"\n\n---\n_记录于 {timestamp}_\n\n{content}"

    with open(path, mode, encoding="utf-8") as f:
        f.write(content)


def load_preload_context(task_id: str, document_id: Optional[str] = None) -> str:
    """
    为新会话构建记忆预加载上下文。

    按优先级合并三个作用域的记忆：
      1. 全局记忆（用户偏好）
      2. 项目记忆（文档相关笔记）
      3. 会话记忆（上次对话摘要）

    Args:
        task_id:     当前会话 ID
        document_id: 当前关联的文档 ID
    Returns:
        合并后的记忆文本（用于注入 System Prompt），空则返回空字符串
    """
    parts = []

    # 1. 全局记忆
    global_mem = read_memory("global")
    if global_mem.strip():
        parts.append(f"【全局记忆 — 用户偏好与通用知识】\n{_truncate(global_mem, 1500)}")

    # 2. 项目记忆
    if document_id:
        project_mem = read_memory("project", document_id)
        if project_mem.strip():
            parts.append(f"【项目记忆 — 文档 {document_id[:8]}... 的历史笔记】\n{_truncate(project_mem, 2000)}")

    # 3. 会话记忆
    session_mem = read_memory("session", task_id)
    if session_mem.strip():
        parts.append(f"【会话记忆 — 上次对话摘要】\n{_truncate(session_mem, 1000)}")

    if not parts:
        return ""

    return "\n\n".join(parts)


def extract_and_save_memory(
    task_id: str,
    document_id: Optional[str],
    conversation_summary: str,
    key_findings: Optional[str] = None,
):
    """
    对话结束后提取关键信息并持久化到记忆文件。

    Args:
        task_id:              会话 ID
        document_id:          关联文档 ID
        conversation_summary: 对话摘要（由 LLM 生成或从历史中提取）
        key_findings:         关键发现（可选，写入项目级记忆）
    """
    # 写入会话记忆
    if conversation_summary.strip():
        write_memory("session", conversation_summary, scope_id=task_id, append=False)

    # 有关键发现时写入项目记忆
    if document_id and key_findings and key_findings.strip():
        write_memory("project", key_findings, scope_id=document_id, append=True)


def _truncate(text: str, max_chars: int) -> str:
    """
    截断文本到指定字符数，保留末尾内容（最新的记忆更重要）。

    Args:
        text:      原始文本
        max_chars: 最大字符数
    Returns:
        截断后的文本
    """
    if len(text) <= max_chars:
        return text
    # 保留末尾（最新记忆），标记截断
    return f"[...前序记忆已截断，保留最近 {max_chars} 字符...]\n\n" + text[-max_chars:]


def init_global_memory():
    """
    初始化全局记忆文件（仅在文件不存在时创建）。
    写入默认的冶金平台用户画像。
    """
    path = _memory_path("global")
    if not os.path.exists(path):
        default_content = (
            "# 小冶全局记忆\n\n"
            "## 用户画像\n"
            "- 身份：冶金工程领域研发人员\n"
            "- 关注领域：高炉炼铁、转炉炼钢、连铸连轧、热处理、金属材料\n"
            "- 偏好语言：中文\n"
            "- 回答风格偏好：专业、具体、有实践意义\n\n"
            "## 积累的关键知识\n"
            "_（随着使用逐步积累...）_\n"
        )
        write_memory("global", default_content, append=False)
