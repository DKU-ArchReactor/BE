from fastapi import APIRouter
from app.schemas.tutor import ExplainRequest, ExplainResponse
from app.services.tutor.rules import explain

router = APIRouter(prefix='/api/v1/tutor', tags=['tutor'])


@router.post('/explain', response_model=ExplainResponse,
             summary='컴파일 전 코드 및 명령어 규칙 해설',
             description='최대 128개 항목의 정적 해설. 실행 결과 조회나 AI 모델 호출은 수행하지 않습니다.')
def explain_items(body: ExplainRequest):
    return ExplainResponse(items=[explain(item) for item in body.items])
