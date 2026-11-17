"""Explicit references to an owned, immutable execution snapshot; no agent tools."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Address = Annotated[int, Field(strict=True, ge=0, le=0xffffffff)]


class ExecutionContextReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    execution_id: UUID
    result_version: Digest
    artifact_sha256: Digest
    mode: Literal['single', 'pipeline']
    # CORE clock is zero-based; cycle 0 means state AFTER the first clock.
    cycle: int = Field(ge=0, le=1999, strict=True)
    memory_addresses: list[Address] = Field(default_factory=list, max_length=16)

    @field_validator('memory_addresses')
    @classmethod
    def aligned_unique_words(cls, values):
        if len(values) != len(set(values)) or any(value % 4 for value in values):
            raise ValueError('Specify unique four-byte-aligned word addresses')
        return values
