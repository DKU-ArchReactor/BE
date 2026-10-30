"""Short-lived capability for one anonymous RV32IM artifact, separate from login JWTs."""
import hashlib
import hmac
import time
import uuid

import jwt
from fastapi import HTTPException

from app.core.config import settings

TOKEN_TTL_SECONDS = 300
TOKEN_AUDIENCE = "archreactor:anonymous-simulation"


def _signing_key() -> bytes:
    secret = settings.JWT_SECRET_KEY
    if not secret or secret == "change-me-jwt-secret":
        raise HTTPException(503, "Anonymous simulation signing is not configured")
    # Domain separation prevents a simulation token from becoming a login token.
    return hmac.new(secret.encode(), TOKEN_AUDIENCE.encode(), hashlib.sha256).digest()


def create_simulation_token(artifact_id: uuid.UUID) -> str:
    now = int(time.time())
    return jwt.encode(
        {"artifact_id": str(artifact_id), "aud": TOKEN_AUDIENCE,
         "iat": now, "exp": now + TOKEN_TTL_SECONDS},
        _signing_key(), algorithm="HS256",
    )


def anonymous_binary_key(token: str) -> str:
    try:
        claims = jwt.decode(
            token, _signing_key(), algorithms=["HS256"], audience=TOKEN_AUDIENCE,
            options={"require": ["artifact_id", "aud", "iat", "exp"]},
        )
        artifact_id = uuid.UUID(claims["artifact_id"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(410, "Simulation token expired; compile again") from None
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "Invalid simulation token") from None
    # Never accept a URL or arbitrary S3 key from the caller.
    return f"builds/anon/{artifact_id}/binary.elf"
