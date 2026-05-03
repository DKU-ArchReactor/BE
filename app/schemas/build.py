import uuid

from pydantic import BaseModel, Field, model_validator


class BuildCompileRequest(BaseModel):
    """POST /api/v1/build/compile 요청 바디.

    `file_id` (저장된 파일 컴파일) 또는 `content` + `lang` (직접 입력 컴파일) 중
    정확히 한 가지 모드만 지정해야 한다.
    """

    file_id: uuid.UUID | None = Field(
        default=None,
        description="컴파일 대상 파일 ID (로그인 + 저장된 파일 모드)",
    )
    content: str | None = Field(
        default=None,
        description="컴파일할 소스 코드 본문 (익명/직접 입력 모드)",
    )
    lang: str | None = Field(
        default=None,
        max_length=16,
        description="언어 식별자 (예: 'c', 'asm'). content 모드에서 필수.",
    )
    compiler_opt: str = Field(
        ...,
        max_length=255,
        description="컴파일러 옵션 문자열 (예: '-O2 -Wall')",
    )

    @model_validator(mode="after")
    def _check_input_mode(self) -> "BuildCompileRequest":
        has_file_id = self.file_id is not None
        has_content = self.content is not None
        if has_file_id and has_content:
            raise ValueError("Specify either file_id or content, not both")
        if not has_file_id and not has_content:
            raise ValueError("One of file_id or content is required")
        if has_content and not self.lang:
            raise ValueError("lang is required when content is provided")
        return self


class BuildCompileResponse(BaseModel):
    """컴파일 실행 결과 — 어셈블리/바이너리는 S3 presigned GET URL로 반환."""

    build_id: uuid.UUID | None = Field(
        None, description="저장된 빌드 ID. 익명(content) 모드는 null."
    )
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
