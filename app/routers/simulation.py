import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.storage import download_bytes
from app.models.build import Build, BuildStatus
from app.models.user import User
from app.services.simulation_service import MAX_ELF, run_simulation

router = APIRouter(prefix='/api/v1/simulation', tags=['simulation'])


class SimulationRequest(BaseModel):
    build_id: uuid.UUID
    mode: Literal['single', 'pipeline'] = 'pipeline'
    max_cycles: int = Field(default=2000, ge=1, le=2000)


def owned_binary(db, user, build_id):
    build = db.get(Build, build_id)
    if build is None:
        raise HTTPException(404, 'Build not found')
    if build.file.project.user_id != user.user_id:
        raise HTTPException(403, 'Access denied')
    if build.status != BuildStatus.success or not build.binary_key:
        raise HTTPException(409, 'Build has no successful ELF artifact')
    return build.binary_key


@router.post('/run')
async def simulate(body: SimulationRequest, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    key = await run_in_threadpool(owned_binary, db, user, body.build_id)
    try:
        elf = await run_in_threadpool(download_bytes, key, MAX_ELF)
    except ValueError:
        raise HTTPException(413, 'ELF exceeds 256 KiB') from None
    return await run_simulation(elf, body.mode, body.max_cycles, request.is_disconnected)
