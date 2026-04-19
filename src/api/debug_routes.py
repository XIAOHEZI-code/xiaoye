from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import os
import uuid
import base64
from typing import List, Any
import json

from src.pipeline.pdf_parser import extract_pdf_with_marker, split_markdown_into_chunk_documents
from src.pipeline.image_analyzer import analyze_metallurgy_image
from src.retrieval.semantic_search import SemanticSearchTool
from src.retrieval.graph_search import GraphLogicTool
from src.agent.graph import create_worker_graph
from langchain_core.messages import HumanMessage

router = APIRouter()

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# 1. Chunks 切分调试接口
@router.post("/chunks/test")
async def test_chunking(file: UploadFile = File(...), chunk_size: int = 1000):
    """
    接受 PDF 文件，运行 Marker 解析，将切割的 Chunks 和图片暂存到 temp 文件夹，并返回分块评估结果。
    """
    try:
        doc_id = str(uuid.uuid4())
        out_dir = os.path.join(TEMP_DIR, doc_id)
        os.makedirs(out_dir, exist_ok=True)
        
        pdf_path = os.path.join(out_dir, "uploaded.pdf")
        with open(pdf_path, "wb") as f:
            f.write(await file.read())
            
        full_text, image_paths, out_metadata = extract_pdf_with_marker(pdf_path, out_dir)
        import os
        from src.pipeline.pdf_parser import split_markdown_into_chunk_documents
        
        # Here we also test image chunks
        from src.models.chunk_document import make_image_chunk
        
        chunk_docs = split_markdown_into_chunk_documents(
            full_text, out_metadata, doc_id=doc_id, source_pdf_id=file.filename, chunk_size=chunk_size
        )
        
        for img_path in image_paths:
            # Add images as ChunkDocuments too
            chunk_docs.append(make_image_chunk(
                description=f"Extracted image from {file.filename}",
                doc_id=doc_id,
                source_pdf_id=file.filename,
                image_uri=img_path,
                page_number=-1,
                bbox=None
            ))
            
        chunks_info = [c.to_dict() for c in chunk_docs]
        
        # 写入评估报告
        report_path = os.path.join(out_dir, "chunk_evaluation.json")
        evaluation = {
            "total_characters": len(full_text),
            "chunk_count": len(chunk_docs),
            "chunk_size_setting": chunk_size,
            "images_extracted": len(image_paths),
            "chunks_preview": chunks_info[:3] # 返回前3个分块看看效果
        }
        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(evaluation, rf, ensure_ascii=False, indent=2)
            
        return {
            "status": "success", 
            "doc_id": doc_id, 
            "temp_folder": out_dir,
            "evaluation": evaluation
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. VLM (QWEN-VL) 功能独立接口
@router.post("/vlm/test")
async def test_vlm(file: UploadFile = File(...)):
    """
    单独测试上传图片，调用 QWEN-VL 进行包含冶金 Ontology 的诊断，并返回强结构化 JSON。
    """
    try:
        content = await file.read()
        b64_img = base64.b64encode(content).decode("utf-8")
        
        result = analyze_metallurgy_image(b64_img)
        return {"status": "success", "result": result.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. 检索全模块联调测试
class RetrievalTestRequest(BaseModel):
    query: str
    top_k: int = 3
    test_graph_entity: str = None # 可选，填入实体名称来测试 GraphRAG

@router.post("/retrieval/test")
async def test_retrieval(req: RetrievalTestRequest):
    """
    同时拨测 Semantic Vector 检索库和 Neo4j 知识图谱库。
    """
    try:
        semantic_tool = SemanticSearchTool()
        vector_results = semantic_tool.search(req.query, top_k=req.top_k)
        
        graph_results = None
        if req.test_graph_entity:
            graph_tool = GraphLogicTool()
            # 查一下上下游所有单跳关系
            graph_results = graph_tool.find_direct_relations(req.test_graph_entity)

        return {
            "query": req.query,
            "semantic_vector_results": vector_results,
            "graph_direct_relations": graph_results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. LangChain (ReAct) 流式监听测试
class StreamChatRequest(BaseModel):
    query: str

@router.post("/langchain/test_stream")
async def test_langchain_stream(req: StreamChatRequest):
    """
    流式监听 LangGraph 每一步（思考、行动、工具观测）。
    非 SSE，直接以 JSON 数组返回全过程的状态机事件。
    """
    import os
    import sys
    import traceback
    
    # 清除代理
    for k in list(os.environ.keys()):
        if 'proxy' in k.lower():
            os.environ.pop(k, None)
    
    try:
        from src.agent.graph import create_worker_graph
        from langchain_core.messages import HumanMessage
        
        agent = create_worker_graph()
        inputs = {"messages": [HumanMessage(content=req.query)]}
        
        event_log = []
        
        # 同步执行（更稳定）
        for event in agent.stream(inputs, stream_mode="values"):
            latest_msg = event.get("messages", [])[-1] if event.get("messages") else None
            if latest_msg:
                log_entry = {
                    "type": latest_msg.__class__.__name__,
                    "content": latest_msg.content[:500] if hasattr(latest_msg, 'content') and latest_msg.content else ""
                }
                if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                    log_entry["tool_calls"] = latest_msg.tool_calls
                event_log.append(log_entry)
                
        return {"status": "success", "trajectory": event_log}
        
    except Exception as e:
        exc_type, exc_value, exc_tb = sys.exc_info()
        error_details = traceback.format_exception(exc_type, exc_value, exc_tb)
        return {
            "status": "error", 
            "message": str(e)[:200], 
            "trajectory": [],
            "trace": error_details[-3:] if len(error_details) >= 3 else error_details
        }
