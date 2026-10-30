import uuid
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.core.database import get_db
from app.core.deps import get_current_user_optional
from app.core.simulation_token import anonymous_binary_key
from app.core.storage import download_bytes
from app.models.build import Build, BuildStatus
from app.models.user import User
from app.services.simulation_service import MAX_ELF, run_simulation

router = APIRouter(prefix='/api/v1/simulation', tags=['simulation'])


class SimulationRequest(BaseModel):
    build_id: uuid.UUID | None = None
    simulation_token: str | None = Field(default=None, min_length=1, max_length=2048)
    mode: Literal['single', 'pipeline'] = 'pipeline'
    max_cycles: int = Field(default=2000, ge=1, le=2000)

    @model_validator(mode='after')
    def check_input_mode(self):
        if (self.build_id is None) == (self.simulation_token is None):
            raise ValueError('Specify exactly one of build_id or simulation_token')
        return self


def owned_binary(db, user, build_id):
    build = db.get(Build, build_id)
    if build is None:
        raise HTTPException(404, 'Build not found')
    if build.file.project.user_id != user.user_id:
        raise HTTPException(403, 'Access denied')
    if build.status != BuildStatus.success or not build.binary_key:
        raise HTTPException(409, 'Build has no successful ELF artifact')
    return build.binary_key


@router.post('/run', description=(
    '로그인 사용자는 build_id, 비로그인 체험은 빌드 응답의 simulation_token으로 실행한다. '
    '두 필드 중 하나만 지정한다. 만료된 토큰은 410을 반환하며 재컴파일해야 한다.'
))
async def simulate(body: SimulationRequest, request: Request,
                   db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    handler_start = time.perf_counter()
    timings = {}
    lookup_start = time.perf_counter()
    if body.simulation_token is not None:
        key = anonymous_binary_key(body.simulation_token)
    else:
        if user is None:
            raise HTTPException(401, 'Authentication required to simulate a saved build',
                                headers={'WWW-Authenticate': 'Bearer'})
        key = await run_in_threadpool(owned_binary, db, user, body.build_id)
    timings['be-lookup'] = (time.perf_counter() - lookup_start) * 1000
    try:
        s3_start = time.perf_counter()
        elf = await run_in_threadpool(download_bytes, key, MAX_ELF)
        timings['s3-read'] = (time.perf_counter() - s3_start) * 1000
    except ValueError:
        raise HTTPException(413, 'ELF exceeds 256 KiB') from None
    result = await run_simulation(elf, body.mode, body.max_cycles, request.is_disconnected, timings=timings)
    prepare_start = time.perf_counter()
    result = jsonable_encoder(result)
    timings['be-json-prepare'] = (time.perf_counter() - prepare_start) * 1000
    encode_start = time.perf_counter()
    content = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    timings['be-json-encode'] = (time.perf_counter() - encode_start) * 1000
    timings['be-handler'] = (time.perf_counter() - handler_start) * 1000
    return Response(content, media_type='application/json', headers={
        'Server-Timing': ', '.join(f'{name};dur={duration:.3f}' for name, duration in timings.items()),
    })
