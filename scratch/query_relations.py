from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    # Query using name
    result = session.run("MATCH (s {name: '304/45钢复合螺栓'})-[r]-(o) RETURN properties(s) as s_props, type(r) as r_type, properties(r) as r_props, properties(o) as o_props")
    print("Relations by Name:")
    for r in result:
        print(f"Rel Type: {r['r_type']}")
        print(f"  Source: {r['s_props'].get('name')}")
        print(f"  Rel properties: {r['r_props']}")
        print(f"  Target: {r['o_props'].get('name')} | properties: {r['o_props']}")
        print("-" * 50)

    # Query using ID
    result2 = session.run("MATCH (s {id: '304/45双金属复合螺栓'})-[r]-(o) RETURN s.name, type(r), o.name")
    print("\nRelations by ID:")
    for r in result2:
        print(r)

driver.close()
