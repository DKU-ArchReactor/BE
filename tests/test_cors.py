import asyncio

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import app


@pytest.mark.parametrize("origin,expected_status", [
    ("https://frontend.example.com", 200),
    ("https://untrusted.example.com", 400),
])
def test_cors_preflight(origin, expected_status, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://frontend.example.com"]')
    settings = Settings(_env_file=None)
    middleware = app.user_middleware[0]
    options = {**middleware.kwargs, "allow_origins": settings.CORS_ORIGINS}
    cors_app = middleware.cls(FastAPI(), **options)
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        responses.append(message)

    asyncio.run(cors_app({
        "type": "http",
        "method": "OPTIONS",
        "path": "/api/v1/files",
        "headers": [
            (b"origin", origin.encode()),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"authorization,content-type"),
        ],
    }, receive, send))
    assert responses[0]["status"] == expected_status
    headers = dict(responses[0]["headers"])
    if expected_status == 200:
        assert headers[b"access-control-allow-origin"] == origin.encode()
    else:
        assert b"access-control-allow-origin" not in headers
