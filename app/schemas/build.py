import uuid

from pydantic import BaseModel, Field


class BuildCompileRequest(BaseModel):
    """POST /api/v1/build/compile 요청 바디."""

    file_id: uuid.UUID = Field(
        ...,
        description="컴파일 대상 파일 ID",
    )
    compiler_opt: str = Field(
        ...,
        max_length=255,
        description="컴파일러 옵션 문자열 (예: '-O2 -Wall')",
    )


class BuildCompileResponse(BaseModel):
    """컴파일 실행 결과 — 어셈블리/바이너리는 S3 presigned GET URL로 반환."""

    build_id: uuid.UUID
    status: str = Field(..., description="success | failed")
    assembly_url: str | None = Field(
        None, description="어셈블리 텍스트 다운로드용 S3 presigned URL (실패 시 null)"
    )
    binary_url: str | None = Field(
        None, description="ELF 바이너리 다운로드용 S3 presigned URL (실패 시 null)"
    )
    log: str | None = Field(None, description="컴파일 stdout/stderr 인라인")


class ObjdumpResponse(BaseModel):
    """objdump 역어셈블 결과 — S3 presigned URL로 반환."""

    file_id: uuid.UUID
    assembly_url: str = Field(..., description="어셈블리 텍스트 S3 presigned URL")


class BuildLogResponse(BaseModel):
    """컴파일 로그 (stdout/stderr) 조회 결과."""

    build_id: uuid.UUID
    stdout: str = ""
    stderr: str = ""
