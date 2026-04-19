import os
import re
from typing import List, Callable
from src.mcp_adapter import mcp_server
from src.agent.tools import get_tools_for_step

# ---------------------------------------------------------
# Claude Pattern: Skill Loader / Heuristic Environmental Context Detector
# Replaces string-based if/else tool assignment by inspecting
# actual file trees, active datasets, or environmental hints
# ---------------------------------------------------------

class SkillLoader:
    def __init__(self, workspace_path: str = "."):
        self.workspace_path = workspace_path
        self.active_skills = []
        
    def probe_environment(self, task_description: str) -> List[Callable]:
        """
        Progressive Disclosure loader: instead of trying to map words like "calculate"
        to specific tools, we now just return the 'always loaded' core tools 
        (e.g. search_available_tools) so the LLM can pull what it needs dynamically.
        """
        # We can still add dynamic MCP plugins here based on file probes if needed
        # but the core LangChain tools are now managed by ToolSearch.
        
        # 1. Base tools (always exposes search_available_tools and core search)
        tools_to_load = get_tools_for_step(task_description)
            
        # 将原始函数包装为 StructuredTool（如果尚未包装）
        from langchain_core.tools import StructuredTool
        from src.agent.tools import ALL_TOOLS
        
        # 建立 name -> StructuredTool 映射
        tool_map = {t.name: t for t in ALL_TOOLS}
        
        result = []
        for item in tools_to_load:
            # 如果是字符串，从 tool_map 获取
            if isinstance(item, str):
                if item in tool_map:
                    result.append(tool_map[item])
            # 如果是函数，用 ALL_TOOLS 找对应的
            elif callable(item):
                for t in ALL_TOOLS:
                    if callable(t.func) and t.func == item:
                        result.append(t)
                        break
            # 如果已经是 StructuredTool
            elif hasattr(item, 'name'):
                result.append(item)
            
        return result
