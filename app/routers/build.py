import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.core.storage import presigned_get_url
from app.core.simulation_token import TOKEN_TTL_SECONDS, create_simulation_token
from app.models.build import Build, BuildStatus
from app.models.user import User
from app.schemas.build import (
    BuildCompileRequest,
    BuildCompileResponse,
    BuildLogResponse,
    BasicCValidationRequest,
    BasicCValidationResponse,
)
from app.services import build_service, file_service
from app.services.tutor import compile_explanations

router = APIRouter(prefix="/api/v1/build", tags=["build"])


@router.post('/validate-c', response_model=BasicCValidationResponse,
             summary='기초 C 문법 범위 검사',
             description='컴파일·실행·저장 없이 main 단일 함수 및 입출력 없는 기초 C 범위를 검사한다.')
def validate_c(body: BasicCValidationRequest):
    diagnostics = build_service.validate_basic_c(body.content)
    return BasicCValidationResponse(valid=not diagnostics, diagnostics=diagnostics)


@router.post(
    "/compile",
    response_model=BuildCompileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="빌드 실행",
    description=(
        "C/ASM 소스 코드를 ELF 바이너리로 컴파일한다. "
        "`file_id`(저장된 파일) 또는 `content` + `lang`(직접 입력) 중 하나로 요청한다. "
        "직접 입력 모드는 인증 없이 사용 가능하며 DB 기록 없이 결과물을 S3에 저장한다. "
        "RV32IM 직접 입력 빌드 성공 시 5분간 유효한 simulation_token을 반환한다."
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
            compile_profile=body.compile_profile,
        )
    except (build_service.UnsupportedLanguageError, build_service.UnsupportedOptionsError) as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    assembly_key, binary_key = build_service.upload_compile_artifacts(
        prefix=f"builds/{build.build_id}", result=result
    )

    build.status = result.status
    build.log = result.log
    build.stdout = result.stdout
    build.stderr = result.stderr
    build.assembly_key = assembly_key
    build.binary_key = binary_key
    db.commit()

    return BuildCompileResponse(
        build_id=build.build_id,
        status=result.status.value,
        assembly_url=presigned_get_url(assembly_key) if assembly_key else None,
        binary_url=presigned_get_url(binary_key) if binary_key else None,
        log=result.log,
        analysis=result.analysis, analysis_error=result.analysis_error,
        diagnostics=result.diagnostics or [],
        tutor=compile_explanations(file.content, file.lang, result.assembly)
        if result.status == BuildStatus.success and body.compile_profile == "rv32im" else None,
    )


def _compile_from_content(body: BuildCompileRequest) -> BuildCompileResponse:
    try:
        result = build_service.compile_source(
            content=body.content,
            lang=body.lang,
            compiler_opt=body.compiler_opt,
            compile_profile=body.compile_profile,
        )
    except (build_service.UnsupportedLanguageError, build_service.UnsupportedOptionsError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    artifact_id = uuid.uuid4()
    simulation_token = None
    if result.status == BuildStatus.success and result.binary is not None and body.compile_profile == "rv32im":
        simulation_token = create_simulation_token(artifact_id)
    prefix = f"builds/anon/{artifact_id}"
    assembly_key, binary_key = build_service.upload_compile_artifacts(
        prefix=prefix, result=result
    )

    return BuildCompileResponse(
        build_id=None,
        simulation_token=simulation_token,
        simulation_token_expires_in=TOKEN_TTL_SECONDS if simulation_token else None,
        status=result.status.value,
        assembly_url=presigned_get_url(assembly_key) if assembly_key else None,
        binary_url=presigned_get_url(binary_key) if binary_key else None,
        log=result.log,
        analysis=result.analysis, analysis_error=result.analysis_error,
        diagnostics=result.diagnostics or [],
        tutor=compile_explanations(body.content, body.lang, result.assembly)
        if result.status == BuildStatus.success and body.compile_profile == "rv32im" else None,
    )


def owned_build(db: Session, user: User, build_id: uuid.UUID) -> Build:
    build = db.get(Build, build_id)
    if build is None:
        raise HTTPException(404, "Build not found")
    if build.file.project.user_id != user.user_id:
        raise HTTPException(403, "Access denied")
    return build


@router.get("/logs", response_model=BuildLogResponse, summary="빌드 로그 조회")
def get_build_logs(build_id: uuid.UUID = Query(...),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    build = owned_build(db, user, build_id)
    return BuildLogResponse(build_id=build.build_id, log=build.log or "",
                            stdout=build.stdout, stderr=build.stderr,
                            streams_available=build.stdout is not None and build.stderr is not None)
