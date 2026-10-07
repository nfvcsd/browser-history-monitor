import hmac
import threading
from typing import Annotated

import requests
from cachecontrol import CacheControl
from fastapi import Header, HTTPException, Request, Depends
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import DeviceEnrollment, Device, User
from .enrollment import credential_hash
from google.auth import exceptions as google_errors
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from .config import get_settings

_transport = threading.local()


def _matches(provided: str | None, expected: str) -> bool:
    return bool(provided and expected) and hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


def require_extension_token(
    request: Request,
    x_extension_token: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> None:
    settings = get_settings()
    if settings.extension_auth_mode == "development":
        if not _matches(x_extension_token, settings.dev_extension_token):
            raise HTTPException(401, "Invalid extension token")
        return
    if not x_device_token or len(x_device_token) > 256:
        raise HTTPException(401, "Device enrollment is required")
    row = db.execute(
        select(DeviceEnrollment, Device, User)
        .join(Device, Device.id == DeviceEnrollment.device_id)
        .join(User, User.id == Device.user_id)
        .where(DeviceEnrollment.credential_hash == credential_hash(x_device_token))
    ).first()
    if not row:
        raise HTTPException(401, "Invalid device credential")
    enrollment, device, user = row
    if enrollment.revoked_at:
        raise HTTPException(403, "Enrollment revoked by administrator")
    if enrollment.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "Device credential expired")
    domains = {
        v.strip().lower()
        for v in settings.extension_workspace_domains.split(",")
        if v.strip()
    }
    if enrollment.hosted_domain not in domains:
        raise HTTPException(403, "Workspace domain is no longer allowed")
    if enrollment.google_subject != user.google_subject:
        raise HTTPException(403, "Enrollment identity no longer matches user")
    request.state.device_identity = {"device_key": device.device_key, "email": user.email}


def enforce_device_identity(request: Request, payload) -> None:
    identity = getattr(request.state, "device_identity", None)
    if identity and (payload.device_key != identity["device_key"] or str(payload.user_email).strip().lower() != identity["email"]):
        raise HTTPException(403, "Upload identity does not match enrolled device")


def verify_google_token(token: str, client_id: str) -> dict:
    # Cache only Google's public signing certificates, honoring their cache headers.
    # Keep requests sessions local to a worker thread; credentials are never cached.
    if not hasattr(_transport, "request"):
        _transport.request = GoogleRequest(session=CacheControl(requests.Session()))

    def bounded_request(*args, **kwargs):
        kwargs["timeout"] = 10
        return _transport.request(*args, **kwargs)

    return id_token.verify_oauth2_token(token, bounded_request, audience=client_id)


def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    settings = get_settings()
    if settings.auth_mode == "development":
        if not _matches(x_admin_token, settings.dev_admin_token):
            raise HTTPException(401, "Invalid development administrator token")
        identity = {
            "mode": "development",
            "sub": "development-admin",
            "email": None,
            "name": "Development administrator",
            "expires_at": None,
        }

        request.state.admin_identity = identity
        return identity

    # Never fall back to development credentials when Google auth is selected.
    if not settings.google_auth_ready:
        raise HTTPException(
            503, "Google sign-in is not configured. Contact your administrator."
        )
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential or len(credential) > 16384:
        raise HTTPException(
            401,
            "Sign in with Google to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = verify_google_token(credential, settings.google_client_id)
    except google_errors.TransportError:
        raise HTTPException(
            503, "Google verification is temporarily unavailable. Please retry."
        )
    except (ValueError, google_errors.GoogleAuthError):
        raise HTTPException(
            401,
            "Google sign-in expired or is invalid. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = claims.get("email")
    hosted_domain = claims.get("hd")
    if (
        claims.get("email_verified") is not True
        or not isinstance(email, str)
        or not isinstance(hosted_domain, str)
        or hosted_domain.lower() not in settings.workspace_domain_set
        or email.lower() not in settings.admin_email_set
    ):
        raise HTTPException(
            403, "This Google account is not an authorized Workspace administrator."
        )
    if (
        not isinstance(claims.get("sub"), str)
        or not claims["sub"]
        or not isinstance(claims.get("exp"), (int, float))
    ):
        raise HTTPException(401, "Invalid Google identity")
    identity = {
        "mode": "google",
        "sub": claims["sub"],
        "email": email.lower(),
        "name": claims.get("name") or email,
        "expires_at": claims["exp"],
    }

    request.state.admin_identity = identity
    return identity
