"""Provider boundary. Execution-context retrieval is intentionally not connected."""
from collections.abc import AsyncIterator
from typing import Protocol
from app.schemas.assistant import ChatRequest
from app.core.config import settings


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AgentProvider(Protocol):
    def stream(self, request: ChatRequest) -> AsyncIterator[dict]:
        """Yield text deltas; implementations must honor cancellation and usage limits."""
        ...


def get_agent_provider() -> AgentProvider | None:
    if not settings.ASSISTANT_ENABLED:
        return None
    if settings.ASSISTANT_PROVIDER == "solid":
        from app.services.tutor.solid import configured_provider
        return configured_provider()
    from app.services.tutor.bedrock import BedrockProvider
    return BedrockProvider()
