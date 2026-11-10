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


def assistant_ready() -> bool:
    # Configuration readiness only; status does not probe the paid/shared gateway.
    return (settings.ASSISTANT_ENABLED and settings.ASSISTANT_PROVIDER == 'solid_llm'
            and bool(settings.SOLID_LLM_API_KEY.get_secret_value().strip()))


def get_agent_provider() -> AgentProvider | None:
    if not assistant_ready():
        return None
    from app.services.assistant.solid_llm import SolidLLMProvider
    return SolidLLMProvider()
