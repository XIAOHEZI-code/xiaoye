import os
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
from typing import List
import json
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from src.core.config import settings

logger = logging.getLogger("xiaoye.ingestion.graph_extractor")

# --- Cypher label/relation whitelist (defense-in-depth) ---
ALLOWED_LABELS = frozenset({"Material", "Property", "Process", "Structure", "Equipment"})
ALLOWED_RELATIONS = frozenset({
    "has_property", "has_structure", "processed_by",
    "uses_equipment", "improves", "degrades",
    "influences", "affects", "contains", "produces",
})


def _normalize_entity(text: str) -> str:
    """Normalize entity name for Neo4j node ID generation."""
    return text.strip().lower().replace(" ", "_")


class Triplet(BaseModel):
    subject: str = Field(description="源实体名称")
    subject_type: str = Field(description="MUST be one of: [Material, Property, Process, Structure, Equipment]")
    relation: str = Field(description="MUST be one of: [has_property, has_structure, processed_by, uses_equipment, improves, degrades, influences, affects, contains, produces]")
    object_: str = Field(description="目标实体名称", alias="object")
    object_type: str = Field(description="MUST be one of: [Material, Property, Process, Structure, Equipment]")
    mechanism: str = Field(default="", description="关系产生的微观机理或原理（如：晶间敏化、碳化物析出），如果没有则为空")
    context: str = Field(default="", description="关系生效的具体上下文或材料对象（如：304不锈钢覆层），如果没有则为空")
class ExtractedGraph(BaseModel):
    triplets: List[Triplet] = Field(description="List of extracted knowledge triplets")

class Neo4jGraphExtractor:
    def __init__(self, use_merged_prompt: bool = False):
        self.use_merged_prompt = use_merged_prompt
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, 
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        self.llm = ChatOpenAI(
            model=settings.DEEP_MODEL,
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
        if self.use_merged_prompt:
            return self.extract_triplets_merged(text_chunk)

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
        5. improves (正向提升: Process/Structure -> Property)
        6. degrades (负向恶化: Process/Structure -> Property)
        7. influences (正向或中性影响: Process/Structure -> Property/Structure)
        8. affects (一般性影响: Process/Structure -> Property/Structure/Process)
        9. contains (包含关系: Structure/Process -> Structure/Element)
        10. produces (产出关系: Process/Equipment -> Material/Structure)

        请输出 JSON 格式，包含一个 'triplets' 列表，每个元素严格包含:
        'subject', 'subject_type', 'relation', 'object', 'object_type', 'mechanism' (产生此关系的机理/原因), 'context' (发生此关系的具体条件/对象材料)。
        
        输入文本：
        "{text_chunk}"
        """
        
        try:
            msg = HumanMessage(content=prompt)
            response = self.llm.invoke([msg])
            
            # Since we enforce json_object response format
            data = json.loads(response.content)
            if isinstance(data, list):
                triplets_data = data
            else:
                triplets_data = data.get("triplets", [])
                
            extracted = [Triplet(**t) for t in triplets_data]
            return self.review_and_normalize_triplets(extracted)
        except Exception as e:
            logger.error(f"Error extracting triplets: {e}", exc_info=True)
            return []

    def extract_triplets_merged(self, text_chunk: str) -> List[Triplet]:
        """
        Combined extraction + normalization in a single LLM call.
        Merges the ontology constraints with normalization rules (translation,
        modifier stripping, synonym merging) into one prompt, reducing LLM calls
        from two to one.
        """
        prompt = f"""
你是一位严谨的冶金知识图谱构建专家。请从以下文本中提取三元组 (Subject, Relation, Object)，并同时进行归一化处理。

【强制约束：消除幻觉 — 实体类型与关系词表】
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
5. improves (正向提升: Process/Structure -> Property)
6. degrades (负向恶化: Process/Structure -> Property)
7. influences (正向或中性影响: Process/Structure -> Property/Structure)
8. affects (一般性影响: Process/Structure -> Property/Structure/Process)
9. contains (包含关系: Structure/Process -> Structure/Element)
10. produces (产出关系: Process/Equipment -> Material/Structure)

【归一化规则】：
1. 翻译与统一定名：将所有的英文专业名词统一翻译为标准中文（例如 "cold-worked 304/45 composite bolts" -> "304/45双金属复合螺栓"）。
2. 剥离状态修饰词：实体名称（subject/object）中不应包含具体的状态或条件定语（如"冷加工态"、"850℃保温"、"淬火后"）。请将这些状态修饰词剥离，并补充到关系(relation)的 `context`（上下文）字段中，保证实体名称的纯洁性。
3. 合并同义词：确保类似 "304/45 钢双金属复合螺栓" 和 "304/45钢复合螺栓" 被统一为最标准、最简洁的名字。

请输出 JSON 格式，包含一个 'triplets' 列表，每个元素严格包含:
'subject', 'subject_type', 'relation', 'object', 'object_type', 'mechanism' (产生此关系的机理/原因), 'context' (发生此关系的具体条件/对象材料)。

输入文本：
"{text_chunk}"
"""
        try:
            msg = HumanMessage(content=prompt)
            response = self.llm.invoke([msg])

            data = json.loads(response.content)
            if isinstance(data, list):
                triplets_data = data
            else:
                triplets_data = data.get("triplets", [])

            if not triplets_data:
                return []

            return [Triplet(**t) for t in triplets_data]
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in merged extraction: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Error in merged extraction: {e}", exc_info=True)
            return []

    def review_and_normalize_triplets(self, triplets: List[Triplet]) -> List[Triplet]:
        """
        Secondary pass to review and normalize entities (translation, stripping modifiers).
        """
        if not triplets:
            return []
        
        # Serialize triplets to JSON string for the prompt
        triplets_json = [t.model_dump(by_alias=True) for t in triplets]
        
        prompt = f"""
        你是一位知识图谱数据清洗专家。请对以下初步抽取出的冶金三元组进行「归一化（Normalization）」审查。
        
        【归一化规则】：
        1. 翻译与统一定名：将所有的英文专业名词统一翻译为标准中文（例如 "cold-worked 304/45 composite bolts" -> "304/45双金属复合螺栓"）。
        2. 剥离状态修饰词：实体名称（subject/object）中不应包含具体的状态或条件定语（如“冷加工态”、“850℃保温”、“淬火后”）。请将这些状态修饰词剥离，并补充到关系(relation)的 `context`（上下文）字段中，保证实体名称的纯洁性。
        3. 合并同义词：确保类似 "304/45 钢双金属复合螺栓" 和 "304/45钢复合螺栓" 被统一为最标准、最简洁的名字。
        4. 保持格式：绝对不要改变原有的 subject_type, object_type, relation 的可选值。
        
        输入的三元组列表（JSON格式）：
        {json.dumps(triplets_json, ensure_ascii=False)}
        
        请输出 JSON 格式，包含一个 'triplets' 列表，里面是清洗并归一化后的三元组，格式与输入严格保持一致。
        """
        
        try:
            msg = HumanMessage(content=prompt)
            response = self.llm.invoke([msg])
            data = json.loads(response.content)
            
            if isinstance(data, list):
                norm_triplets = data
            else:
                norm_triplets = data.get("triplets", [])
                
            return [Triplet(**t) for t in norm_triplets]
        except Exception as e:
            logger.error(f"Error normalizing triplets: {e}", exc_info=True)
            return triplets  # Fallback to original if error occurs

    @staticmethod
    def load_triplets_to_neo4j(triplets: List[Triplet], doc_id: str, driver):
        """
        Injects the extracted triplets into the Neo4j Graph DB with dynamic labels and edges.

        Args:
            triplets: List of Triplet objects to load
            doc_id: Document ID for provenance tracking
            driver: Neo4j GraphDatabase.driver instance
        """
        with driver.session() as session:
            for t in triplets:
                # Basic ID generation from names, production would do better entity resolution
                sub_id = _normalize_entity(t.subject)
                obj_id = _normalize_entity(t.object_)
                if not sub_id or not obj_id:
                    continue
                
                # Strip spaces for Cypher label interpolation. WHITELIST VALIDATED above.
                s_label = t.subject_type.replace(" ", "")
                o_label = t.object_type.replace(" ", "")
                r_type = t.relation.replace(" ", "").upper()
                
                # --- Defense-in-depth: whitelist validation ---
                if s_label not in ALLOWED_LABELS or o_label not in ALLOWED_LABELS:
                    raise ValueError(
                        f"Invalid entity type in triplet: "
                        f"subject_type=`{t.subject_type}`, object_type=`{t.object_type}`"
                    )
                if t.relation not in ALLOWED_RELATIONS:
                    raise ValueError(f"Invalid relation type: `{t.relation}`")

                query = f"""
                MERGE (s:{s_label} {{id: $sub_id}})
                ON CREATE SET s.name = $sub_name
                
                MERGE (o:{o_label} {{id: $obj_id}})
                ON CREATE SET o.name = $obj_name
                
                MERGE (s)-[r:{r_type} {{doc_id: $doc_id}}]->(o)
                ON CREATE SET r.mechanism = $mechanism, r.context = $context, r.weight = 1
                ON MATCH SET r.mechanism = $mechanism, r.context = $context, r.weight = coalesce(r.weight, 1) + 1
                """
                    
                session.run(
                    query, 
                    sub_id=sub_id, sub_name=t.subject,
                    obj_id=obj_id, obj_name=t.object_,
                    doc_id=doc_id,
                    mechanism=t.mechanism,
                    context=t.context
                )


