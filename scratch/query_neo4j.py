from neo4j import GraphDatabase
from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

with driver.session() as session:
    result = session.run("MATCH (n) RETURN labels(n) as labels, n.name as name, n.id as id LIMIT 100")
    for r in result:
        print(f"Labels: {r['labels']}, Name: {r['name']}, ID: {r['id']}")

driver.close()
