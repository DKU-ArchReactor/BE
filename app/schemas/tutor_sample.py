from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

class TutorSampleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=256)

    @field_validator('message')
    @classmethod
    def validate_message(cls, value):
        if not value.strip() or len(value.encode('utf-8')) > 1024:
            raise ValueError('message must be nonblank and at most 1024 UTF-8 bytes')
        return value

class TutorSampleResponse(BaseModel):
    request_id: UUID
    schema_version: Literal['1.0']
    tutor_version: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=256)
    reply: str = Field(min_length=1, max_length=2048)
    sample: Literal[True]
