import os
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
from typing import List
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from src.core.config import settings

class Triplet(BaseModel):
    subject: str = Field(description="源实体名称")
    subject_type: str = Field(description="MUST be one of: [Material, Property, Process, Structure, Equipment]")
    relation: str = Field(description="MUST be one of: [has_property, has_structure, processed_by, uses_equipment, affects]")
    object_: str = Field(description="目标实体名称", alias="object")
    object_type: str = Field(description="MUST be one of: [Material, Property, Process, Structure, Equipment]")

class ExtractedGraph(BaseModel):
    triplets: List[Triplet] = Field(description="List of extracted knowledge triplets")

class Neo4jGraphExtractor:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, 
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        self.llm = ChatOpenAI(
            model="qwen-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            model_kwargs={"response_format": {"type": "json_object"}}
        )

    def close(self):
        self.driver.close()

    def extract_triplets_from_text(self, text_chunk: str) -> List[Triplet]:
        """
        Uses Qwen LLM to extract metallurgy-specific entity-relation triplets using a STRICT ontology.
        """
        prompt = f"""
        你是一位严谨的冶金知识图谱构建专家。请从以下文本中提取三元组 (Subject, Relation, Object)。
        【强制约束：消除幻觉】
        为了保证图谱的规范性，你提取的实体类型和关系必须严格限制在以下 Ontology 词表中：
        
        [实体类型 Entity Types]: 
        1. Material (材料/合金/元素, e.g. "Q345钢", "奥氏体")
        2. Property (性能/参数, e.g. "抗拉强度", "淬透性")
        3. Process (工艺/处理方法, e.g. "退火", "热轧")
        4. Structure (微观组织/缺陷, e.g. "马氏体", "位错", "夹杂物")
        5. Equipment (设备/仪表, e.g. "高炉", "冷轧机")
        
        [关系类型 Relations]:
        1. has_property (具有性能: Material -> Property)
        2. has_structure (含有组织: Material -> Structure)
        3. processed_by (经过工艺: Material -> Process)
        4. uses_equipment (使用设备: Process -> Equipment)
        5. affects (影响: Process/Structure -> Property)
        
        请输出 JSON 格式，包含一个 'triplets' 列表，每个元素严格包含:
        'subject', 'subject_type', 'relation', 'object', 'object_type'。
        
        输入文本：
        "{text_chunk}"
        """
        
        try:
            msg = HumanMessage(content=prompt)
            response = self.llm.invoke([msg])
            
            # Since we enforce json_object response format
            data = json.loads(response.content)
            triplets = data.get("triplets", [])
            return [Triplet(**t) for t in triplets]
        except Exception as e:
            print(f"Error extracting triplets: {e}")
            return []

    def load_triplets_to_neo4j(self, triplets: List[Triplet], doc_id: str):
        """
        Injects the extracted triplets into the Neo4j Graph DB.
        """
        query = (
            "MERGE (s:Entity {id: $subject_id, name: $subject_name}) "
            "MERGE (o:Entity {id: $object_id, name: $object_name}) "
            "MERGE (s)-[r:RELATION {type: $relation_type, doc_id: $doc_id}]->(o)"
        )

        with self.driver.session() as session:
            for t in triplets:
                # Basic ID generation from names, production would do better entity resolution
                sub_id = self._normalize_entity(t.subject)
                obj_id = self._normalize_entity(t.object_)
                if not sub_id or not obj_id:
                    continue
                    
                session.run(
                    query, 
                    subject_id=sub_id, subject_name=t.subject,
                    object_id=obj_id, object_name=t.object_,
                    relation_type=t.relation,
                    doc_id=doc_id
                )

    def _normalize_entity(self, text: str) -> str:
        return text.strip().lower().replace(" ", "_")
