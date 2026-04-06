import os
import re
from typing import List, Callable
from src.mcp_adapter import mcp_server

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
        Claude's loadSkillsDir behavior: don't just guess tools by string,
        check the actual workspace footprint to load valid MCP plugins.
        """
        tools_to_load = []
        
        # 1. Probe for structural patterns
        # For Metallurgy, does the folder contain .csv exports?
        has_csv_files = any(f.endswith('.csv') for f in os.listdir(self.workspace_path))
        if has_csv_files or "表格" in task_description or "数据分析" in task_description:
            tools_to_load.append(self._mock_data_analysis_tool)
            
        # 2. Probe for SQL schema definitions
        has_db_schema = os.path.exists(os.path.join(self.workspace_path, "create_db.py"))
        if has_db_schema and ("查询" in task_description or "数据库" in task_description):
            tools_to_load.append(self._mock_sql_agent_tool)
            
        hints = []
        # 3. Always include foundational text/graph if specifically requested
        if re.search(r"文献|标准|原理|概念", task_description):
            hints.append("text")
        if re.search(r"关系|影响|因果", task_description):
            hints.append("graph")
            
        # 4. Probe for Mathematics / PyCalphad calculations
        if re.search(r"计算|方程|动力学|热力学|吉布斯|相图|预测|数值", task_description):
            hints.append("calculation")
            
        # If absolutely no context detected, fallback to general Text Search
        if not hints:
            hints.append("general")
            
        # Pull actual callables remotely from the MCP Server Registry
        fetched_tools = mcp_server.get_callable_tools(hints)
        tools_to_load.extend(fetched_tools)
            
        return list(set(tools_to_load)) # Deduplicate

    # --- Stand-in mock tools for the newly discovered domains ---
    
    @staticmethod
    def _mock_data_analysis_tool(csv_path: str, instruction: str) -> str:
        """Analyze local standard CSV files using Pandas."""
        return "Executed Pandas dataframe analysis."

    @staticmethod
    def _mock_sql_agent_tool(sql_query: str) -> str:
        """Execute a READ-ONLY SQL query against the metallurgy property database."""
        # Represents the AGENT TO SQL capability
        return "Executed SQL query successfully."
