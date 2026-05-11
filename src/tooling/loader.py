"""
Tooling Loader — 环境探测式工具装填引擎

[M5 迁移] 从 src/agent/skill_loader.py 迁移至 src/tooling/loader.py
通过 ToolRegistry 接口提供工具，不直接 import 工具定义。
"""

import os
from typing import List, Callable
from langchain_core.tools import BaseTool


class ToolLoader:
    """环境探测式工具装填器 — 通过 ToolRegistry 接口工作"""

    def __init__(self, workspace_path: str = "."):
        self.workspace_path = workspace_path

    def probe_environment(self, task_description: str) -> List[BaseTool]:
        """
        Progressive Disclosure loader: 返回 'always loaded' 核心工具，
        让 LLM 通过 search_available_tools 按需拉取更多工具。

        通过 ToolRegistry 接口获取工具，不直接 import 工具定义。
        """
        from src.tooling.registry import get_tool_registry

        registry = get_tool_registry()
        return registry.get_tools_for_task(task_description)
