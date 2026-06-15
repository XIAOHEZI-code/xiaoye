from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    # Update the HAS_PROPERTY relationship to '高抗拉强度'
    query = """
    MATCH (s {name: '304/45钢复合螺栓'})-[r:HAS_PROPERTY]->(o {name: '高抗拉强度'})
    SET r.context = '分别对 35K碳钢螺栓和冷加工态 304/45 钢复合螺栓进行拉伸试验,抗拉强度平均值分别为 578 和 593 MPa。',
        r.mechanism = '冷变形强化作用提高了材料的整体抗拉强度。'
    RETURN count(r) as updated_count
    """
    res = session.run(query)
    count = res.single()["updated_count"]
    print(f"Updated {count} HAS_PROPERTY relations in Neo4j.")

driver.close()
