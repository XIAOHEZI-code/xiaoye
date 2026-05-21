import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.api.swarm_routes import router as swarm_router
from src.api.debug_routes import router as debug_router
from src.api.upload_routes import router as upload_router
from src.api.chat_routes import router as chat_router
from src.api.askuser_routes import router as askuser_router
from src.api.graph_routes import router as graph_router

app = FastAPI(
    title="Xiaoye Metallurgy AI Platform",
    description="人机协作式的冶金领域开发/研究平台 API Gateway",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    """确保数据库表在应用启动时创建，并初始化全局日志"""
    from src.core.logger import setup_logger

    logger = setup_logger("xiaoye.system")
    logger.info("Initializing Xiaoye AI Platform...")

    from src.db.session import engine, Base
    from src.models.document import DocumentMetadata, ImageEvaluation  # noqa: F401 — 触发模型注册

    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables verified/created")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 M3 核心异步并行业务路由 (FastAPI SSE Engine)
app.include_router(swarm_router, prefix="/api/v1")

# 上传路由
app.include_router(upload_router, prefix="/api/v1", tags=["Upload"])

# Chat 路由
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])

# AskUser 路由（AI 主动求问断点）
app.include_router(askuser_router, prefix="/api/v1", tags=["AskUser"])

# 知识图谱路由
app.include_router(graph_router, prefix="/api/v1", tags=["Graph"])

# 知识图谱去重路由
from src.api.graph_dedup_routes import router as graph_dedup_router
app.include_router(graph_dedup_router, prefix="/api/v1", tags=["Graph Dedup"])

# 仅保留测试用例路由
app.include_router(debug_router, prefix="/api/v1/debug", tags=["Debug & Testing"])

# ── 裁剪图片静态服务（Fork VLM 选区截图） ──
cropped_images_dir = os.path.join(os.path.dirname(__file__), "data", "cropped_images")
os.makedirs(cropped_images_dir, exist_ok=True)
app.mount(
    "/api/images", StaticFiles(directory=cropped_images_dir), name="cropped_images"
)
print(f"✅ 裁剪图片目录已挂载: {cropped_images_dir}")

# ── 承载前端静态文件（SPA 单页应用） ──
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    print(f"✅ 前端静态文件已挂载: {frontend_dist}")
    print(f"   → 访问 http://localhost:8000/ 即可使用前端界面")
else:
    print(f"⚠️ 前端构建目录不存在: {frontend_dist}")
    print(f"   请先执行: cd frontend && npm run build")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
