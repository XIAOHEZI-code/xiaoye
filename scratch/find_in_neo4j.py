from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    # Search nodes
    result_nodes = session.run("MATCH (n) WHERE any(key in keys(n) WHERE toString(n[key]) CONTAINS '578' OR toString(n[key]) CONTAINS '593') RETURN labels(n) as labels, properties(n) as props")
    print("Nodes containing 578 or 593:")
    for r in result_nodes:
        print(r)

    # Search relationships
    result_rels = session.run("MATCH ()-[r]->() WHERE any(key in keys(r) WHERE toString(r[key]) CONTAINS '578' OR toString(r[key]) CONTAINS '593') RETURN type(r) as type, properties(r) as props, startNode(r).name as start, endNode(r).name as end")
    print("\nRelationships containing 578 or 593:")
    for r in result_rels:
        print(f"Rel Type: {r['type']}")
        print(f"  Start Node: {r['start']}")
        print(f"  End Node: {r['end']}")
        print(f"  Props: {r['props']}")
        print("-" * 50)

driver.close()
