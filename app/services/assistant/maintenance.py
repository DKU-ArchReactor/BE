"""Small periodic expiry sweeper; no model calls or payload logging."""
import asyncio
from contextlib import asynccontextmanager
import logging

from starlette.concurrency import run_in_threadpool
from app.core.database import SessionLocal
from app.services.assistant.context import purge_expired

logger = logging.getLogger(__name__)


def sweep():
    with SessionLocal() as db:
        purge_expired(db)


async def sweep_loop():
    while True:
        try:
            await run_in_threadpool(sweep)
        except Exception:
            # No exception text: connection strings can contain credentials.
            logger.warning('assistant_context_cleanup_failed')
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(sweep_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
