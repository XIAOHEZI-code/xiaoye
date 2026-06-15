from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    result = session.run("MATCH (s {name: '304/45钢复合螺栓'})-[r]->(o) WHERE o.name CONTAINS '抗拉' OR o.name CONTAINS '强度' RETURN properties(s) as s_props, type(r) as r_type, properties(r) as r_props, properties(o) as o_props")
    for r in result:
        print(f"Rel Type: {r['r_type']}")
        print(f"  Target: {r['o_props'].get('name')} | properties: {r['o_props']}")
        print(f"  Rel properties: {r['r_props']}")
        print("-" * 50)

driver.close()
