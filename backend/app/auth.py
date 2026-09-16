import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def _matches(provided: str | None, expected: str) -> bool:
    return bool(provided) and hmac.compare_digest(provided, expected)


def require_extension_token(
    x_extension_token: str | None = Header(default=None),
) -> None:
    if not _matches(x_extension_token, get_settings().dev_extension_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid extension token",
        )


def require_admin_token(
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not _matches(x_admin_token, get_settings().dev_admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
        )
