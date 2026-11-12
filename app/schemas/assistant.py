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


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    context: ExecutionContextReference | None = None
    _execution_context: dict | None = PrivateAttr(default=None)

    @model_validator(mode='after')
    def validate_conversation(self):
        if self.messages[0].role != 'user' or self.messages[-1].role != 'user':
            raise ValueError('Conversation must start and end with a user message')
        if sum(len(message.content) for message in self.messages) > 24000:
            raise ValueError('Conversation exceeds 24000 characters')
        return self
