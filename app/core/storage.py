from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.core.config import settings


@lru_cache(maxsize=1)
def _client() -> BaseClient:
    kwargs: dict = {
        "region_name": settings.AWS_REGION,
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
        ),
    }
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(
        Bucket=settings.AWS_S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def presigned_get_url(key: str, expires: int | None = None) -> str:
    return _client().generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.AWS_S3_BUCKET, "Key": key},
        ExpiresIn=expires or settings.S3_PRESIGN_EXPIRES_SECONDS,
    )
