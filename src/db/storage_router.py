"""
统一存储路由模块（Storage Router）。

职责：接收上游解析/分析管线的结构化产出物，按数据类型自动路由到对应物理存储：
- 知识图谱三元组 → Neo4j
- 图像二进制 + 元数据 → 本地磁盘 + PostgreSQL (ImageEvaluation)

注意：图像分类已迁移至 src/ingestion/image_analyzer.py 的两阶段 VLM 管线。
      本模块不再做关键词匹配分类，分类信息由上游通过 vlm_results 参数注入。
"""

import os
import base64
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from neo4j import GraphDatabase
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.logger import setup_logger
from src.db.session import SessionLocal
from src.models.document import ImageEvaluation
from src.ingestion.graph_extractor import _normalize_entity

logger = setup_logger("xiaoye.db.storage_router")

# Standard label/relation whitelist (defense-in-depth validation)
ALLOWED_LABELS = frozenset({"Material", "Property", "Process", "Structure", "Equipment"})
ALLOWED_RELATIONS = frozenset({
    "has_property", "has_structure", "processed_by",
    "uses_equipment", "improves", "degrades",
    "influences", "affects", "contains", "produces",
})

class GraphData(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]


def save_knowledge_graph(triplet_list: List[Any], doc_id: Optional[str] = None) -> int:
    """
    统一保存三元组数据到图数据库 Neo4j 中，对外部屏蔽 Cypher 语句的细节。
    内部逻辑判定：由于是图谱结构化三元组，自动分发到 Neo4j 物理存储。
    
    Args:
        triplet_list: 三元组列表，其元素可以是字典，或者是包含 subject, subject_type 等属性的 Pydantic 模型。
        doc_id: 关联的文档ID，用于溯源。如果为 None，则默认使用 "global_storage_router"。
        
    Returns:
        int: 成功保存的关系数量。
    """
    doc_id = doc_id or "global_storage_router"
    if not triplet_list:
        logger.info("No triplets provided to save_knowledge_graph.")
        return 0

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    count = 0
    try:
        with driver.session() as session:
            for t in triplet_list:
                # 提取三元组各个字段，兼容对象和字典格式
                if isinstance(t, dict):
                    subject = t.get("subject")
                    subject_type = t.get("subject_type")
                    relation = t.get("relation")
                    object_ = t.get("object_") or t.get("object")
                    object_type = t.get("object_type")
                    mechanism = t.get("mechanism", "")
                    context = t.get("context", "")
                else:
                    subject = getattr(t, "subject", None)
                    subject_type = getattr(t, "subject_type", None)
                    relation = getattr(t, "relation", None)
                    object_ = getattr(t, "object_", None) or getattr(t, "object", None)
                    object_type = getattr(t, "object_type", None)
                    mechanism = getattr(t, "mechanism", "")
                    context = getattr(t, "context", "")

                if not subject or not object_ or not relation:
                    logger.warning(f"Skipping invalid triplet: {t}")
                    continue

                sub_id = _normalize_entity(subject)
                obj_id = _normalize_entity(object_)
                if not sub_id or not obj_id:
                    continue

                # 替换空格，符合 Cypher 语法
                s_label = subject_type.replace(" ", "")
                o_label = object_type.replace(" ", "")
                r_type = relation.replace(" ", "").upper()

                # 防御性白名单校验
                if s_label not in ALLOWED_LABELS or o_label not in ALLOWED_LABELS:
                    raise ValueError(
                        f"Invalid entity type in triplet: "
                        f"subject_type=`{subject_type}`, object_type=`{object_type}`"
                    )
                if relation not in ALLOWED_RELATIONS:
                    raise ValueError(f"Invalid relation type: `{relation}`")

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
                    sub_id=sub_id, sub_name=subject,
                    obj_id=obj_id, obj_name=object_,
                    doc_id=doc_id,
                    mechanism=mechanism,
                    context=context
                )
                count += 1
                
        logger.info(f"Successfully saved {count} relationships to Neo4j.")
        return count
    finally:
        driver.close()


def save_raw_assets(
    media_assets: List[Any], 
    doc_id: Optional[str] = None, 
    filename: Optional[str] = None,
    vlm_results: Optional[List[Any]] = None
) -> List[str]:
    """
    解码富媒体资产（图片），保存到本地物理磁盘，并将其分析元数据和文件路径同步存储在 PostgreSQL 关系数据库中。
    内部逻辑判定并分发：二进制文件保存至磁盘，结构化元数据保存至 PostgreSQL。
    
    Args:
        media_assets: 富媒体资产列表，包含图像二进制数据（Base64编码）、文件名等。
        doc_id: 关联的文档ID。若为 None，默认使用 "global_assets"。
        filename: 源文件名。用于推导本地存储的子文件夹。
        vlm_results: VLM 两阶段管线（image_analyzer.py）产出的分析结果列表，
                     与 media_assets 按索引一一对应。用于提取图像分类信息。
        
    Returns:
        List[str]: 所有已保存图像的本地物理绝对路径。
    """
    doc_id = doc_id or "global_assets"
    if not media_assets:
        return []

    # 确定保存路径
    if filename:
        basename = os.path.splitext(os.path.basename(filename))[0]
    else:
        basename = doc_id
        
    target_img_dir = os.path.join("data/marker_output", basename)
    os.makedirs(target_img_dir, exist_ok=True)

    saved_paths = []
    db = SessionLocal()
    
    try:
        for i, asset in enumerate(media_assets):
            # 兼容对象和字典
            if isinstance(asset, dict):
                image_base64 = asset.get("image_base64")
                image_filename = asset.get("image_filename")
                caption = asset.get("caption", "")
                context_above = asset.get("context_above", "")
                context_below = asset.get("context_below", "")
                description = asset.get("description", "")
            else:
                image_base64 = getattr(asset, "image_base64", None)
                image_filename = getattr(asset, "image_filename", None)
                caption = getattr(asset, "caption", "")
                context_above = getattr(asset, "context_above", "")
                context_below = getattr(asset, "context_below", "")
                description = getattr(asset, "description", "")

            if not image_base64 or not image_filename:
                logger.warning("Skipping asset due to missing image_base64 or image_filename.")
                continue

            img_path = os.path.join(target_img_dir, image_filename)
            abs_img_path = os.path.abspath(img_path)
            
            # 保存到物理磁盘
            try:
                with open(img_path, "wb") as img_f:
                    img_f.write(base64.b64decode(image_base64))
                saved_paths.append(abs_img_path)
            except Exception as e:
                logger.error(f"Failed to save image file to disk: {e}")
                continue

            # 图像分类已迁移至上游 VLM 两阶段管线 (image_analyzer.py)，不再在本模块做关键词匹配
            vlm_result = vlm_results[i] if vlm_results and i < len(vlm_results) else None
            if vlm_result:
                category = getattr(vlm_result, "category", None) or "general"
            else:
                category = "general"

            # 存入 PostgreSQL 关系型数据库 (ImageEvaluation)
            db_eval = ImageEvaluation(
                document_id=doc_id,
                image_path=abs_img_path,
                category=category,
                evaluation_text=description or caption or "No description provided",
                raw_json={
                    "caption": caption,
                    "context_above": context_above,
                    "context_below": context_below
                }
            )
            db.add(db_eval)
            
        db.commit()
        logger.info(f"Successfully processed and stored {len(saved_paths)} raw assets.")
        return saved_paths
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while saving assets: {e}")
        raise
    finally:
        db.close()


def query_entity_relations(entity_name: str) -> GraphData:
    """
    通过 Neo4j 查询指定实体的一阶关系，同时测量并记录执行延迟（要求延迟在 100ms 内）。
    
    Args:
        entity_name: 实体名称。
        
    Returns:
        GraphData: 包含 nodes 列表与 links 列表的数据。
    """
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    entity_id = _normalize_entity(entity_name)
    
    # 匹配与该实体相连的任何有向关系 (s)-[r]->(o)
    query = """
    MATCH (s)-[r]->(o)
    WHERE s.name = $entity_name OR s.id = $entity_id OR toLower(s.name) = toLower($entity_name)
       OR o.name = $entity_name OR o.id = $entity_id OR toLower(o.name) = toLower($entity_name)
    RETURN s, r, o
    """
    
    nodes_dict = {}
    links = []
    
    start_time = time.perf_counter()
    try:
        with driver.session() as session:
            result = session.run(query, entity_name=entity_name, entity_id=entity_id)
            for record in result:
                s = record["s"]
                o = record["o"]
                r = record["r"]
                
                # 获取节点 ID
                def get_node_id(node):
                    if hasattr(node, "element_id") and node.element_id:
                        return node.element_id
                    if hasattr(node, "id") and node.id is not None:
                        return str(node.id)
                    return node.get("id", "Unknown")
                
                # 添加节点到字典以去重
                for node in (s, o):
                    node_id = get_node_id(node)
                    if node_id not in nodes_dict:
                        labels = list(node.labels) if hasattr(node, "labels") else []
                        nodes_dict[node_id] = {
                            "id": node_id,
                            "name": node.get("name", node.get("id", "Unknown")),
                            "val": 1,
                            "label": labels[0] if labels else "Unknown"
                        }
                
                # 添加关系
                links.append({
                    "source": get_node_id(s),
                    "target": get_node_id(o),
                    "type": r.type if hasattr(r, "type") else "RELATED_TO",
                    "mechanism": r.get("mechanism", ""),
                    "context": r.get("context", ""),
                    "doc_id": r.get("doc_id", "")
                })
        
        latency = (time.perf_counter() - start_time) * 1000
        logger.info(f"Query entity relations for '{entity_name}' took {latency:.2f}ms")
        
        # 验证延迟在 100ms 内
        if latency > 100.0:
            logger.warning(f"Query latency exceeded 100ms threshold: {latency:.2f}ms")
            
        return GraphData(
            nodes=list(nodes_dict.values()),
            links=links
        )
    except Exception as e:
        logger.error(f"Error querying entity relations: {e}")
        raise
    finally:
        driver.close()
