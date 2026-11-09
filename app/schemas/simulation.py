"""Simulation API models; CORE result fields are preserved without filtering."""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class SimulationRequest(BaseModel):
    build_id: uuid.UUID | None = Field(default=None, description="로그인 사용자가 소유한 성공 빌드 ID")
    simulation_token: str | None = Field(default=None, min_length=1, max_length=2048,
                                        description="직접 입력 컴파일 응답의 익명 실행 토큰")
    mode: Literal["single", "pipeline"] = Field(default="pipeline", description="실행할 CORE 엔진")
    max_cycles: int = Field(default=2000, ge=1, le=2000, strict=True)

    @model_validator(mode="after")
    def check_input_mode(self):
        if (self.build_id is None) == (self.simulation_token is None):
            raise ValueError("Specify exactly one of build_id or simulation_token")
        return self


class SimulationResponse(BaseModel):
    request_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    execution_status: Literal["COMPLETED", "CYCLE_LIMIT", "SIMULATION_ERROR"]
    core_version: str = Field(min_length=1)
    result_schema_version: str = Field(min_length=1)
    result: dict[str, Any] = Field(description="CORE JSON 원문 구조: initial_state, program, simulator, summary, history, console_output 등")
    tutor: dict[str, Any] | None = Field(default=None, description="규칙 기반 명령어 및 사이클 이벤트 해설 (schema_version 1.0)")
