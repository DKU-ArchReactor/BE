from fastapi import APIRouter, Request
from app.schemas.tutor_sample import TutorSampleRequest, TutorSampleResponse
from app.services import tutor_client

router = APIRouter(prefix='/api/v1/tutor', tags=['tutor'])

@router.post('/sample', response_model=TutorSampleResponse,
    summary='TUTOR gRPC 연결 확인용 샘플',
    description='공개 연결 확인 API. AI 모델 호출, 코드 실행, DB 접근을 하지 않습니다. 최대 256자.')
async def sample(body: TutorSampleRequest, request: Request):
    return await tutor_client.sample(body.message, disconnected=request.is_disconnected)
