from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


from app.schemas.execution_context import ExecutionContextReference


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


class EditorSource(BaseModel):
    """Untrusted current editor text, captured for this question only."""
    model_config = ConfigDict(extra='forbid', strict=True)
    language: Literal['c', 'asm']
    content: str = Field(min_length=1, max_length=12000)

    @field_validator('content')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Editor source must not be blank')
        if len(value.encode('utf-8')) > 48000:
            raise ValueError('Editor source exceeds byte limit')
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    context: ExecutionContextReference | None = None
    editor_source: EditorSource | None = None
    _execution_context: dict | None = PrivateAttr(default=None)
    _request_id: str | None = PrivateAttr(default=None)
    _processing_stage: str = PrivateAttr(default="admission")

    @model_validator(mode='after')
    def validate_conversation(self):
        if self.messages[0].role != 'user' or self.messages[-1].role != 'user':
            raise ValueError('Conversation must start and end with a user message')
        if sum(len(message.content) for message in self.messages) > 24000:
            raise ValueError('Conversation exceeds 24000 characters')
        return self
