import json
from src.tooling.search_engine import get_tool_search_engine

# ---------------------------------------------------------
# Pseudo-MCP (Model Context Protocol) Server Adapter
# Acts as a microservice boundary between the SkillLoader
# and the actual physical execution of Python/Tool functions.
# ---------------------------------------------------------

class MCPRegistryAdapter:
    def list_tools(self, domain_hints: list) -> list:
        """
        Acts like mcp.list_tools() returning JSON schemas.
        Simulates an API endpoint.
        """
        engine = get_tool_search_engine()
        # Mock behavior: Just return everything the engine knows about
        # In a real MCP scenario, this would query a remote service
        mcp_schemas = []
        for name in engine._registry.keys():
            mcp_schemas.append({
                "name": name,
                "description": engine._registry[name].description,
            })
        return mcp_schemas

    def get_callable_tools(self, domain_hints: list) -> list:
        """
        For localized LangChain runtime, returns actual tool callables.
        In a fully decoupled architecture, this would return remote proxy stubs.
        Note: The progressive disclosure engine now handles tool loading,
        so this just returns an empty list for now to represent 0 remote tools.
        """
        return []

    def call_tool(self, name: str, arguments: dict):
        """Acts like mcp.call_tool() - execute remotely."""
        engine = get_tool_search_engine()
        target_tool = engine.get_tool_callable(name)
        
        if not target_tool:
            return {"error": f"Tool {name} not found in MCP Server."}
            
        try:
            result = target_tool.invoke(arguments)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Export the singleton server instance
mcp_server = MCPRegistryAdapter()
