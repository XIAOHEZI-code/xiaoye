import networkx as nx

class GraphMergeDealer:
    """
    Utility for incrementally merging Knowledge Sub-graphs (extacted per chunk) 
    into a larger Document Graph or Global Graph.
    This acts as the staging area before executing Cypher transactions to Neo4j.
    """
    def __init__(self, separator="<SEP>"):
        self.separator = separator

    def get_from_to(self, node1, node2):
        return (node1, node2) if node1 < node2 else (node2, node1)

    def merge_subgraph(self, base_graph: nx.Graph, new_graph: nx.Graph) -> nx.Graph:
        """
        Merges `new_graph` into `base_graph` in place.
        Consolidates node descriptions and sums up edge weights.
        """
        # 1. Merge Nodes
        for node_name, attr in new_graph.nodes(data=True):
            if not base_graph.has_node(node_name):
                base_graph.add_node(node_name, **attr)
                continue
                
            # If node exists, consolidate descriptions and source references
            node = base_graph.nodes[node_name]
            
            if "description" in attr:
                existing_desc = node.setdefault("description", "")
                if existing_desc:
                    node["description"] = existing_desc + self.separator + attr["description"]
                else:
                    node["description"] = attr["description"]
                    
            if "source_id" in attr:
                existing_src = node.setdefault("source_id", "")
                if existing_src:
                    # RAGFlow assumes source_id is a string concatenation. Lists might be safer.
                    # We keep string concatenation for compatibility if separated by sep
                    node["source_id"] = existing_src + "," + attr["source_id"]
                else:
                    node["source_id"] = attr["source_id"]

        # 2. Merge Edges
        for source, target, attr in new_graph.edges(data=True):
            source, target = self.get_from_to(source, target)
            edge = base_graph.get_edge_data(source, target)
            
            if edge is None:
                base_graph.add_edge(source, target, **attr)
                continue
                
            # If edge exists, accumulate weights and consolidate descriptions
            edge["weight"] = edge.setdefault("weight", 0.0) + attr.get("weight", 1.0)
            
            if "description" in attr:
                existing_desc = edge.setdefault("description", "")
                if existing_desc:
                    edge["description"] = existing_desc + self.separator + attr["description"]
                else:
                    edge["description"] = attr["description"]
                    
            if "keywords" in attr:
                existing_kwd = edge.setdefault("keywords", "")
                if existing_kwd and attr["keywords"]:
                    edge["keywords"] = existing_kwd + "," + attr["keywords"]
                elif attr["keywords"]:
                    edge["keywords"] = attr["keywords"]

            if "source_id" in attr:
                existing_src = edge.setdefault("source_id", "")
                if existing_src:
                    edge["source_id"] = existing_src + "," + attr["source_id"]
                else:
                    edge["source_id"] = attr["source_id"]

        # 3. Compute Degree for PageRank weighting locally
        for node_id, degree in base_graph.degree:
            base_graph.nodes[node_id]["rank"] = int(degree)

        return base_graph

    def generate_cypher_queries(self, graph: nx.Graph) -> list[str]:
        """
        [Xiaoye Custom] Converts the staging NetworkX graph into Cypher MERGE queries
        for ingestion into Neo4j.
        """
        queries = []
        # Nodes
        for node_name, attr in graph.nodes(data=True):
            entity_type = attr.get("entity_type", "Entity").replace(" ", "_").replace("-", "")
            desc = attr.get("description", "").replace("'", "\\'")
            queries.append(
                f"MERGE (n:{entity_type} {{name: '{node_name}'}}) "
                f"ON CREATE SET n.description = '{desc}', n.rank = {attr.get('rank', 0)} "
                f"ON MATCH SET n.description = n.description + '{self.separator}' + '{desc}', n.rank = {attr.get('rank', 0)}"
            )
            
        # Edges
        for source, target, attr in graph.edges(data=True):
            weight = attr.get("weight", 1.0)
            desc = attr.get("description", "").replace("'", "\\'")
            queries.append(
                f"MATCH (a {{name: '{source}'}}), (b {{name: '{target}'}}) "
                f"MERGE (a)-[r:RELATED_TO]->(b) "
                f"ON CREATE SET r.weight = {weight}, r.description = '{desc}' "
                f"ON MATCH SET r.weight = r.weight + {weight}, r.description = r.description + '{self.separator}' + '{desc}'"
            )
        return queries

if __name__ == '__main__':
    # Test incremental merge and cypher generation
    g1 = nx.Graph()
    g1.add_node("马氏体", entity_type="Material", description="硬度高", source_id="doc1")
    g1.add_node("淬火", entity_type="Process", description="加热然后冷却", source_id="doc1")
    g1.add_edge("马氏体", "淬火", weight=1.0, description="马氏体通过淬火形成", source_id="doc1")
    
    g2 = nx.Graph()
    g2.add_node("马氏体", entity_type="Material", description="含碳量高", source_id="doc2")
    g2.add_node("退火", entity_type="Process", description="降低硬度", source_id="doc2")
    g2.add_edge("马氏体", "退火", weight=1.0, description="退火降低马氏体硬度", source_id="doc2")
    g2.add_edge("马氏体", "淬火", weight=0.5, description="强化晶格", source_id="doc2")
    
    dealer = GraphMergeDealer()
    merged = dealer.merge_subgraph(g1, g2)
    
    print(f"Nodes: {merged.number_of_nodes()}, Edges: {merged.number_of_edges()}")
    print("Cypher:")
    for c in dealer.generate_cypher_queries(merged):
        print("  ", c)
