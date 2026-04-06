import json
from src.agent.tools import TOOL_REGISTRY

# ---------------------------------------------------------
# Pseudo-MCP (Model Context Protocol) Server Adapter
# Acts as a microservice boundary between the SkillLoader
# and the actual physical execution of Python/Tool functions.
# ---------------------------------------------------------

class MCPRegistryAdapter:
    def __init__(self):
        # We hold all tools internally
        self.registry = {}
        for category, tools in TOOL_REGISTRY.items():
            for t in tools:
                self.registry[t.name] = t

    def list_tools(self, domain_hints: list) -> list:
        """
        Acts like mcp.list_tools() returning JSON schemas.
        Simulates an API endpoint.
        """
        selected_tool_names = set()
        
        for hint in domain_hints:
            if hint in TOOL_REGISTRY:
                for t in TOOL_REGISTRY[hint]:
                    selected_tool_names.add(t.name)
        
        mcp_schemas = []
        for name in selected_tool_names:
            t = self.registry[name]
            mcp_schemas.append({
                "name": name,
                "description": t.description,
                "schema": t.args_schema.schema() if t.args_schema else {}
            })
        return mcp_schemas

    def get_callable_tools(self, domain_hints: list) -> list:
        """
        For localized LangChain runtime, returns actual tool callables.
        In a fully decoupled architecture, this would return remote proxy stubs.
        """
        selected = set()
        for hint in domain_hints:
            if hint in TOOL_REGISTRY:
                selected.update(TOOL_REGISTRY[hint])
        return list(selected)

    def call_tool(self, name: str, arguments: dict):
        """Acts like mcp.call_tool() - execute remotely."""
        target_tool = self.registry.get(name)
        
        if not target_tool:
            return {"error": f"Tool {name} not found in MCP Server."}
            
        try:
            result = target_tool.invoke(arguments)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Export the singleton server instance
mcp_server = MCPRegistryAdapter()
