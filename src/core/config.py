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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
