from fastapi import APIRouter, Depends, Response

from ..auth import require_admin_token
from ..config import get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.get("/config")
def auth_config(response: Response):
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    return {
        "mode": settings.auth_mode,
        "google_client_id": (
            settings.google_client_id if settings.auth_mode == "google" else None
        ),
        "configured": (
            settings.google_auth_ready
            if settings.auth_mode == "google"
            else bool(settings.dev_admin_token)
        ),
    }


@router.get("/me")
def current_admin(response: Response, identity: dict = Depends(require_admin_token)):
    response.headers["Cache-Control"] = "no-store"
    return identity
