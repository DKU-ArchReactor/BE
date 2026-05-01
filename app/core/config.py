from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "ArchReactor"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/archreactor"
    SECRET_KEY: str = "change-me-in-production"

    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    AWS_REGION: str = "ap-northeast-2"
    AWS_S3_BUCKET: str = ""
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_PRESIGN_EXPIRES_SECONDS: int = 300

    class Config:
        env_file = ".env"


settings = Settings()
