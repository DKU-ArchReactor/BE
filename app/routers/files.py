import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.file import FileCreate, FileDetail, FileSummary
from app.services import file_service

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.get(
    "",
    response_model=list[FileSummary],
    summary="파일 목록 조회",
    description="사용자가 보유한 모든 소스 코드 파일의 요약 목록을 반환한다.",
    response_description="파일 요약 정보 리스트",
)
def list_files(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return file_service.list_files(db, user)


@router.get(
    "/{file_id}",
    response_model=FileDetail,
    summary="파일 열기",
    description="특정 소스 코드의 상세 내용(본문 포함)을 조회한다.",
    response_description="파일 상세 정보",
)
def get_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return file_service.get_file(db, file_id, user)
    except file_service.FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except file_service.FileAccessDeniedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")


@router.post(
    "",
    response_model=FileDetail,
    status_code=status.HTTP_201_CREATED,
    summary="코드 저장",
    description="새로운 소스 코드를 저장하거나 기존 코드를 업데이트한다.",
    response_description="저장된 파일 상세 정보",
)
def create_or_update_file(
    body: FileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return file_service.upsert_file(db, user, body)


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="파일 삭제",
    description="특정 저장 파일을 삭제한다. 연관된 빌드 결과물도 함께 삭제된다.",
    response_description="삭제 완료 (빈 응답)",
)
def delete_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        file_service.delete_file(db, file_id, user)
    except file_service.FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except file_service.FileAccessDeniedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
