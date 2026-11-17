from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.models import user as _user_model  # noqa: F401 — register with Base.metadata
from app.routers import auth as auth_router
from app.routers import assistant as assistant_router
from app.routers import tutor as tutor_router
from app.routers import tutor_sample as tutor_sample_router
from app.routers import build as build_router
from app.routers import files as files_router
from app.routers import simulation as simulation_router
from app.routers import professor as professor_router

from app.services.assistant.telemetry import configure_usage_logging
from app.services.assistant.maintenance import lifespan

configure_usage_logging()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router.router)
app.include_router(professor_router.router)
app.include_router(files_router.router)
app.include_router(build_router.router)
app.include_router(tutor_router.router)
app.include_router(tutor_sample_router.router)
app.include_router(assistant_router.router)
app.include_router(simulation_router.router)


@app.get("/")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
