from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Project
    PROJECT_NAME: str = "Xiaoye Metallurgy Agent"
    VERSION: str = "1.0.0"
    
    # PostgreSQL
    POSTGRES_USER: str = "xiaoye_user"
    POSTGRES_PASSWORD: str = "xiaoye_password"
    POSTGRES_DB: str = "xiaoye_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis / Celery
    REDIS_HOST: str = "localhost"
    REDIS_PORT: str = "6379"

    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    # Elasticsearch
    ES_HOST: str = "localhost"
    ES_PORT: str = "9200"

    @property
    def ELASTICSEARCH_URL(self) -> str:
        return f"http://{self.ES_HOST}:{self.ES_PORT}"
        
    # Neo4j Graph DB
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "xiaoye_neo4j"

    # File Storage
    UPLOAD_DIR: str = "data/storage"

    # External APIs
    QWEN_API_KEY: Optional[str] = None
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_EMBEDDING_MODEL: str = "text-embedding-v3"

    # ── 模型常量（单一真相源）──────────────────────────────────────────────

    # ══════════════════════════════════════════════════════════════════════
    # ⚠️ 模型下线公告 (Deprecation Notice)
    # ══════════════════════════════════════════════════════════════════════
    # 以下模型将于 2026-07-13 由阿里云百炼平台正式下线：
    #   qwen-turbo, qwen-turbo-realtime, qwen-vl-max, qwen-vl-plus,
    #   qwq-plus, qvq-max, qvq-plus, qwen-math-turbo,
    #   qwen-coder-turbo, qwen-coder-plus
    #
    # 以下模型将于 2026-09-08 由阿里云百炼平台正式下线：
    #   qwen3-vl-flash
    # ══════════════════════════════════════════════════════════════════════

    # ── 模型迁移待办 ──
    # [x] FAST_MODEL: qwen-turbo → qwen3.6-flash (2026-06-15)
    # [x] VLM_MODEL: qwen-vl-plus → qwen3.7-plus (2026-06-15)
    # [x] VLM_AGENT_MODEL: qwen3-vl-flash → qwen3.6-flash (2026-06-15, 提前规避 09-08 下线)
    # [ ] DEEP_MODEL: qwen-plus 当前安全，可择机升级到 qwen3.7-plus

    # ── 两阶段 VLM 图像分析模型 ──
    # Stage 1: 图像预分类 — 快速/便宜模型做类型判断和关注点生成
    VLM_PRE_ANALYZER_MODEL: str = "qwen3.6-flash"

    # Stage 2: 深度分析 — 按预分析指引做详细领域分析（Qwen3.7 旗舰统一模型）
    VLM_DEEP_ANALYZER_MODEL: str = "qwen3.7-plus"

    # 路由 / 闲聊 / Fast RAG（纯文本）— 原 qwen-turbo 已于 2026-07-13 下线，迁移至 Flash 系列
    FAST_MODEL: str = "qwen3.6-flash"
    # ReAct 深度推理（纯文本，无图）
    DEEP_MODEL: str = "qwen-plus"
    # 纯视觉分析（直接分析 Fork）— 原 qwen-vl-plus 已于 2026-07-13 下线，改用 Qwen3.7 统一模型（原生支持图文）
    VLM_MODEL: str = "qwen3.7-plus"
    # 多模态 Agent（深度分析 Fork，有图 + tool calling）— 原 qwen3-vl-flash 将于 2026-09-08 下线，提前迁移至 qwen3.6-flash
    VLM_AGENT_MODEL: str = "qwen3.6-flash"
    # 代码生成 / 知识图谱 JSON 抽取（高指令遵循要求）
    # 替代 qwen-max（下线）→ qwen3.6-plus（官方推荐，支持 Structured Output）
    # 如需更强推理能力可换为 qwen3.7-plus
    CODE_MODEL: str = "qwen3.6-plus"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
