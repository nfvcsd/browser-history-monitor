import hmac
import threading
from typing import Annotated

import requests
from cachecontrol import CacheControl
from fastapi import Header, HTTPException, Request
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
    x_extension_token: str | None = Header(default=None),
) -> None:
    if not _matches(x_extension_token, get_settings().dev_extension_token):
        raise HTTPException(401, "Invalid extension token")


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
