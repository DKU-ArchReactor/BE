import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)

    @field_validator('content')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Message must not be blank')
        return value


class ExecutionReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    build_id: uuid.UUID
    mode: Literal['single', 'pipeline'] = 'pipeline'
    max_cycles: int = Field(default=2000, ge=1, le=2000)
    history_index: int = Field(ge=0, le=1999)


class ChatRequest(BaseModel):
    _context_metadata: dict | None = PrivateAttr(default=None)
    model_config = ConfigDict(extra='forbid')
    execution: ExecutionReference | None = None
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def validate_conversation(self):
        if self.messages[0].role != 'user' or self.messages[-1].role != 'user':
            raise ValueError('Conversation must start and end with a user message')
        if sum(len(message.content) for message in self.messages) > 24000:
            raise ValueError('Conversation exceeds 24000 characters')
        return self
