"""
ToolRegistry — 工具管线的核心接口协议

定义 Agent/Reasoning 管线消费工具的唯一契约。
Reasoning 管线只通过此接口获取工具，不直接 import 工具定义文件。

设计要点：
  1. ABC 定义标准接口
  2. DefaultToolRegistry 提供默认实现（基于现有工具集）
  3. 全局单例通过 get_tool_registry() 获取
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from langchain_core.tools import BaseTool


class ToolRegistry(ABC):
    """工具注册表抽象接口 — Reasoning 管线与 Tooling 管线的唯一桥梁"""

    @abstractmethod
    def get_all_tools(self) -> List[BaseTool]:
        """获取全量工具列表（ToolNode 需要）"""
        ...

    @abstractmethod
    def get_tools_for_task(self, task_description: str) -> List[BaseTool]:
        """根据任务描述获取初始暴露的最小工具集（渐进式披露）"""
        ...

    @abstractmethod
    def get_always_loaded_tools(self) -> List[BaseTool]:
        """获取始终加载的核心工具（如搜索工具 + 工具发现入口）"""
        ...


class DefaultToolRegistry(ToolRegistry):
    """
    默认工具注册表实现 — 包装现有 tools.py 的全部工具。

    惰性初始化：首次调用时才 import 工具定义，
    避免模块级别的循环依赖。
    """

    def __init__(self):
        self._all_tools: Optional[List[BaseTool]] = None
        self._initialized = False

    def _ensure_init(self):
        """惰性加载工具定义"""
        if not self._initialized:
            from src.tooling.definitions import ALL_TOOLS, get_tools_for_step
            self._all_tools = ALL_TOOLS
            self._get_tools_for_step = get_tools_for_step
            self._initialized = True

    def get_all_tools(self) -> List[BaseTool]:
        self._ensure_init()
        return self._all_tools

    def get_tools_for_task(self, task_description: str) -> List[BaseTool]:
        """渐进式工具装载：核心工具 + search_available_tools"""
        self._ensure_init()
        raw_tools = self._get_tools_for_step(task_description)

        # 确保返回的都是 StructuredTool 实例
        from langchain_core.tools import StructuredTool
        tool_map = {t.name: t for t in self._all_tools}

        result = []
        for item in raw_tools:
            if isinstance(item, str):
                if item in tool_map:
                    result.append(tool_map[item])
            elif callable(item) and not isinstance(item, BaseTool):
                for t in self._all_tools:
                    if hasattr(t, 'func') and t.func == item:
                        result.append(t)
                        break
            elif isinstance(item, BaseTool):
                result.append(item)

        return result

    def get_always_loaded_tools(self) -> List[BaseTool]:
        self._ensure_init()
        return self.get_tools_for_task("")


# ── 全局单例 ──────────────────────────────────────────────────

_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表单例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = DefaultToolRegistry()
    return _global_registry


def set_tool_registry(registry: ToolRegistry):
    """替换全局工具注册表（用于测试或自定义实现）"""
    global _global_registry
    _global_registry = registry
