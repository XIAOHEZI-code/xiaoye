from neo4j import GraphDatabase
from typing import List, Dict, Any
from src.core.config import settings

class GraphLogicTool:
    """
    Tool for traversing the knowledge graph to fetch multi-hop deductive paths.
    Particularly useful when the Agent is tracing causal relationships (e.g. Process -> Property).
    """

    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, 
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

    def find_direct_relations(self, entity_name: str, direction: str = "both") -> List[Dict[str, Any]]:
        """
        Finds immediate relationships connected to an entity.
        Direction can be 'out', 'in', or 'both'.
        """
        entity_id = self._normalize_entity(entity_name)
        
        if direction == "out":
            match_clause = "(s {id: $entity_id})-[r]->(o)"
        elif direction == "in":
            match_clause = "(s)-[r]->(o {id: $entity_id})"
        else:
            match_clause = "(s {id: $entity_id})-[r]-(o)"

        query = f"""
        MATCH {match_clause}
        RETURN labels(s)[0] AS s_label, s.name AS subject, type(r) AS relation, r.mechanism AS mechanism, r.context AS context, labels(o)[0] AS o_label, o.name AS object, r.doc_id AS source_doc
        LIMIT 20
        """

        results = []
        with self.driver.session() as session:
            records = session.run(query, entity_id=entity_id)
            for record in records:
                results.append({
                    "subject": f"{record['subject']} ({record['s_label']})",
                    "relation": record["relation"],
                    "object": f"{record['object']} ({record['o_label']})",
                    "mechanism": record["mechanism"],
                    "context": record["context"],
                    "source_doc": record["source_doc"]
                })
        return results

    def trace_impact_path(self, start_entity: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """
        Finds how a specific entity (like a Process or Structure) ripples outwards.
        e.g., How does 'Quenching' affect other things in the graph up to 3 hops away.
        """
        entity_id = self._normalize_entity(start_entity)
        
        # Variable length path traversal
        query = f"""
        MATCH p = (start {{id: $entity_id}})-[*1..{max_hops}]->(end)
        RETURN [x IN nodes(p) | x.name] AS path_nodes, [r IN relationships(p) | type(r)] AS path_relations
        LIMIT 10
        """

        results = []
        with self.driver.session() as session:
            records = session.run(query, entity_id=entity_id)
            for record in records:
                results.append({
                    "nodes": record["path_nodes"],
                    "relations": record["path_relations"]
                })
        return results

    def _normalize_entity(self, text: str) -> str:
        return text.strip().lower().replace(" ", "_")
