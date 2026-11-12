from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
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

    TUTOR_GRPC_TARGET: str = ""
    TUTOR_GRPC_TIMEOUT_SECONDS: float = Field(default=5.0, ge=0.1, le=30)

    CORE_GRPC_TARGET: str = ""
    CORE_GRPC_TIMEOUT_SECONDS: float = 12.0
    CORE_RESULT_SCHEMA_MAJOR: str = "1"

    AWS_REGION: str = "ap-northeast-2"
    ASSISTANT_ENABLED: bool = False
    ASSISTANT_PROVIDER: Literal["solid_llm"] = "solid_llm"
    SOLID_LLM_BASE_URL: str = "https://dku-chat.kloud.zone/llm/v1"
    SOLID_LLM_MODEL: str = Field(default="local/qwen3-coder-next", min_length=1, max_length=256)
    SOLID_LLM_API_KEY: SecretStr = SecretStr("")
    # Verified on the current gateway; missing usage still remains unknown.
    SOLID_LLM_INCLUDE_USAGE: bool = True
    # Verified with the current SOLID model. Re-probe when gateway/model changes.
    SOLID_LLM_CLASSIFICATION_FORMAT: Literal["none", "json_schema"] = "json_schema"
    ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS: float = Field(default=10, ge=1, le=30)
    ASSISTANT_MAX_TOKENS: int = Field(default=2048, ge=1, le=4096)
    ASSISTANT_TIMEOUT_SECONDS: float = Field(default=60, ge=5, le=120)
    ASSISTANT_CONTEXT_TTL_SECONDS: int = Field(default=1800, ge=60, le=3600)
    ASSISTANT_CONTEXT_MAX_SNAPSHOTS: int = Field(default=3, ge=1, le=5)
    ASSISTANT_DAILY_REQUESTS: int = Field(default=50, ge=1, le=1000)
    ASSISTANT_COOLDOWN_SECONDS: int = Field(default=10, ge=1, le=60)
    AWS_S3_BUCKET: str = ""
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_PRESIGN_EXPIRES_SECONDS: int = 300

    @field_validator("SOLID_LLM_BASE_URL")
    @classmethod
    def secure_gateway_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("SOLID_LLM_BASE_URL must be an HTTPS URL without credentials, query or fragment")
        return value.rstrip("/")

    class Config:
        env_file = ".env"


settings = Settings()
