import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user_optional
from app.core.storage import presigned_get_url
from app.models.build import Build
from app.models.user import User
from app.schemas.build import (
    BuildCompileRequest,
    BuildCompileResponse,
    BuildLogResponse,
    ObjdumpResponse,
)
from app.services import build_service, file_service

router = APIRouter(prefix="/api/v1/build", tags=["build"])


@router.post(
    "/compile",
    response_model=BuildCompileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="빌드 실행",
    description=(
        "C/ASM 소스 코드를 ELF 바이너리로 컴파일한다. "
        "`file_id`(저장된 파일) 또는 `content` + `lang`(직접 입력) 중 하나로 요청한다. "
        "직접 입력 모드는 인증 없이도 사용 가능하며 빌드 결과는 영속화되지 않는다."
    ),
    response_description="컴파일 상태와 결과물 URL",
)
def compile_file(
    body: BuildCompileRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if body.file_id is not None:
        return _compile_from_file(db, user, body)
    return _compile_from_content(body)


def _compile_from_file(
    db: Session, user: User | None, body: BuildCompileRequest
) -> BuildCompileResponse:
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authentication required to compile a saved file",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        file = file_service.get_file(db, body.file_id, user)
    except file_service.FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except file_service.FileAccessDeniedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

    build = Build(file_id=file.file_id)
    db.add(build)
    db.flush()

    try:
        result = build_service.compile_source(
            content=file.content,
            lang=file.lang,
            compiler_opt=body.compiler_opt,
        )
    except build_service.UnsupportedLanguageError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    assembly_key, binary_key = build_service.upload_compile_artifacts(
        prefix=f"builds/{build.build_id}", result=result
    )

    build.status = result.status
    build.log = result.log
    build.assembly_key = assembly_key
    build.binary_key = binary_key
    db.commit()

    return BuildCompileResponse(
        build_id=build.build_id,
        status=result.status.value,
        assembly_url=presigned_get_url(assembly_key) if assembly_key else None,
        binary_url=presigned_get_url(binary_key) if binary_key else None,
        log=result.log,
    )


def _compile_from_content(body: BuildCompileRequest) -> BuildCompileResponse:
    try:
        result = build_service.compile_source(
            content=body.content,
            lang=body.lang,
            compiler_opt=body.compiler_opt,
        )
    except build_service.UnsupportedLanguageError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    prefix = f"builds/anon/{uuid.uuid4()}"
    assembly_key, binary_key = build_service.upload_compile_artifacts(
        prefix=prefix, result=result
    )

    return BuildCompileResponse(
        build_id=None,
        status=result.status.value,
        assembly_url=presigned_get_url(assembly_key) if assembly_key else None,
        binary_url=presigned_get_url(binary_key) if binary_key else None,
        log=result.log,
    )


@router.get(
    "/objdump",
    response_model=ObjdumpResponse,
    summary="역어셈블",
    description="빌드된 ELF 바이너리의 기계어를 어셈블리어로 변환하여 반환한다.",
    response_description="objdump 결과 텍스트",
)
def objdump_file(
    file_id: uuid.UUID = Query(..., description="역어셈블 대상 파일 ID"),
):
    # TODO: 최신 성공 빌드의 binary_path 를 objdump 실행 후 텍스트 반환
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented")


@router.get(
    "/logs",
    response_model=BuildLogResponse,
    summary="로그 조회",
    description="지정된 빌드의 컴파일 에러 및 경고 메시지(stdout/stderr)를 조회한다.",
    response_description="빌드 로그 텍스트",
)
def get_build_logs(
    build_id: uuid.UUID = Query(..., description="조회할 빌드 ID"),
):
    # TODO: build_id 로 저장된 로그 파일/컬럼 읽어 반환
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented")
