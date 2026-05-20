from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from neo4j import GraphDatabase
from src.core.config import settings

router = APIRouter()

class GraphData(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]

@router.get("/graph", response_model=GraphData)
async def get_knowledge_graph(limit: int = 200):
    """
    Fetches the knowledge graph data (nodes and edges) from Neo4j
    formatted for D3/react-force-graph visualization.
    """
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    query = """
    MATCH (n)-[r]->(m)
    WITH n, r, m LIMIT $limit
    RETURN n, r, m
    """
    
    nodes_dict = {}
    links = []
    
    try:
        with driver.session() as session:
            result = session.run(query, limit=limit)
            for record in result:
                n = record["n"]
                m = record["m"]
                r = record["r"]
                
                # Add nodes
                for node in (n, m):
                    node_id = node.element_id
                    if node_id not in nodes_dict:
                        labels = list(node.labels)
                        nodes_dict[node_id] = {
                            "id": node_id,
                            "name": node.get("name", node.get("id", "Unknown")),
                            "val": 1,
                            "label": labels[0] if labels else "Unknown"
                        }
                
                # Add links
                links.append({
                    "source": n.element_id,
                    "target": m.element_id,
                    "type": r.type,  # The actual Neo4j relation type
                    "mechanism": r.get("mechanism", ""),
                    "context": r.get("context", "")
                })
                
        driver.close()
        return GraphData(
            nodes=list(nodes_dict.values()),
            links=links
        )
    except Exception as e:
        driver.close()
        raise HTTPException(status_code=500, detail=f"Neo4j query failed: {e}")
