"""Versioned tutor contracts; presentation colors stay in the client."""
from typing import Literal, Protocol
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ExplainItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['c', 'asm', 'crt']
    text: str = Field(max_length=4096)
    line: int = Field(default=1, ge=1, le=1000000)
    pc: str | None = Field(default=None, max_length=32)


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[ExplainItem] = Field(min_length=1, max_length=128)


class RuleExplanation(BaseModel):
    kind: Literal['c', 'asm', 'crt']
    category: str
    title: str
    summary: str
    detail: str
    opcode: str | None = None
    operands: str | None = None


class ExplainResponse(BaseModel):
    schema_version: Literal['1.0'] = '1.0'
    items: list[RuleExplanation]


class ContextReference(BaseModel):
    """Reserved for a future authorized, read-only execution context provider."""
    execution_id: UUID
    mode: Literal['single', 'pipeline']
    cycle: int | None = Field(default=None, ge=0)
    source_line: int | None = Field(default=None, ge=1)


class ContextProvider(Protocol):
    async def resolve(self, reference: ContextReference, *, user_id: UUID) -> dict:
        """Implementations must check ownership before retrieving any execution data."""
        ...
