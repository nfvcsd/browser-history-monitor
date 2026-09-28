from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routes.admin import router as admin_router
from .routes.auth import router as auth_router
from .routes.audit import router as audit_router
from .routes.activity import router as activity_router, sync_router as activity_sync_router
from .routes.sync import router as sync_router
from .routes.reports import router as reports_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Milestone 1 only. Replace with Alembic before production.
    Base.metadata.create_all(bind=engine)
    yield


settings = get_settings()

app = FastAPI(
    title="Browser History Monitor API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token", "X-Extension-Token", "Authorization"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(sync_router)
app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(activity_router)
app.include_router(activity_sync_router)
app.include_router(admin_router)
app.include_router(reports_router)
