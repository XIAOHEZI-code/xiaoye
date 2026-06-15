from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    result = session.run("MATCH ()-[r]->() WHERE any(key in keys(r) WHERE toString(r[key]) CONTAINS '18.9' OR toString(r[key]) CONTAINS '2.8' OR toString(r[key]) CONTAINS '30.4') RETURN type(r) as type, properties(r) as props, startNode(r).name as start, endNode(r).name as end")
    for r in result:
        print(f"Rel Type: {r['type']}")
        print(f"  Start Node: {r['start']}")
        print(f"  End Node: {r['end']}")
        print(f"  Props: {r['props']}")
        print("-" * 50)

driver.close()
