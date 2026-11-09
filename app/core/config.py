from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "ArchReactor"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/archreactor"
    SECRET_KEY: str = "change-me-in-production"

    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # JSON array, e.g. ["https://app.example.com", "http://localhost:5173"]
    CORS_ORIGINS: list[str] = []

    CORE_GRPC_TARGET: str = ""
    CORE_GRPC_TIMEOUT_SECONDS: float = 12.0
    CORE_RESULT_SCHEMA_MAJOR: str = "1"

    AWS_REGION: str = "ap-northeast-2"
    ASSISTANT_ENABLED: bool = False
    BEDROCK_MODEL_ID: str = "anthropic.claude-sonnet-5"
    BEDROCK_MAX_TOKENS: int = Field(default=2048, ge=1, le=4096)
    ASSISTANT_TIMEOUT_SECONDS: float = Field(default=60, ge=5, le=120)
    ASSISTANT_DAILY_REQUESTS: int = Field(default=50, ge=1, le=1000)
    ASSISTANT_COOLDOWN_SECONDS: int = Field(default=10, ge=1, le=60)
    AWS_S3_BUCKET: str = ""
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_PRESIGN_EXPIRES_SECONDS: int = 300

    class Config:
        env_file = ".env"


settings = Settings()
