from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.swarm_routes import router as swarm_router
from src.api.debug_routes import router as debug_router
from src.api.upload_routes import router as upload_router
from src.api.chat_routes import router as chat_router
from src.api.askuser_routes import router as askuser_router

app = FastAPI(
    title="Xiaoye Metallurgy AI Platform",
    description="人机协作式的冶金领域开发/研究平台 API Gateway",
    version="1.0.0"
)

@app.on_event("startup")
def on_startup():
    """确保数据库表在应用启动时创建"""
    from src.db.session import engine, Base
    from src.models.document import DocumentMetadata, ImageEvaluation  # noqa: F401 — 触发模型注册
    Base.metadata.create_all(bind=engine)
    print("[Startup] ✅ Database tables verified/created")

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

# 仅保留测试用例路由
app.include_router(debug_router, prefix="/api/v1/debug", tags=["Debug & Testing"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
