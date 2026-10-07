from contextlib import asynccontextmanager
import asyncio
import logging
from starlette.concurrency import run_in_threadpool
from .collection import cleanup_retention
from .db import SessionLocal
from .routes.settings import router as settings_router, reads as settings_reads, collection_router

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routes.admin import router as admin_router
from .routes.auth import router as auth_router
from .routes.audit import router as audit_router
from .routes.activity import router as activity_router, sync_router as activity_sync_router
from .routes.enrollment import router as enrollment_router
from .routes.sync import router as sync_router
from .routes.reports import router as reports_router


def retention_pass():
    with SessionLocal() as db:
        cleanup_retention(db)


async def retention_loop():
    while True:
        try:
            await run_in_threadpool(retention_pass)
        except Exception:
            logging.getLogger(__name__).exception("Retention cleanup failed; retrying in five minutes")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Milestone 1 only. Replace with Alembic before production.
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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
    allow_headers=["Content-Type", "X-Admin-Token", "X-Extension-Token", "X-Device-Token", "Authorization"],
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

app.include_router(settings_router)
app.include_router(settings_reads)
app.include_router(collection_router)

app.include_router(enrollment_router)
