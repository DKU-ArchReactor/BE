"""실행 컨텍스트 분석기: future read-only context contract, not connected."""
from typing import Literal, Protocol
from uuid import UUID
from pydantic import BaseModel, Field

class ExecutionContextReference(BaseModel):
    """Reserved for a future authorized, read-only execution context provider."""
    execution_id: UUID
    mode: Literal['single', 'pipeline']
    cycle: int | None = Field(default=None, ge=0)
    source_line: int | None = Field(default=None, ge=1)


class ExecutionContextProvider(Protocol):
    async def resolve(self, reference: ExecutionContextReference, *, user_id: str) -> dict:
        """Implementations must check ownership before retrieving any execution data."""
        ...
