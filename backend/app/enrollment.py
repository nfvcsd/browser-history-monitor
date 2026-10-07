"""Google-verified profile enrollment. This is not physical-device attestation."""

import hashlib
import time

import requests
from fastapi import HTTPException

from .config import get_settings


def credential_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify_extension_identity(token):
    settings = get_settings()
    clients = {
        v.strip() for v in settings.extension_google_client_ids.split(",") if v.strip()
    }
    domains = {
        v.strip().lower()
        for v in settings.extension_workspace_domains.split(",")
        if v.strip()
    }
    if not clients or not domains:
        raise HTTPException(
            503, "Automatic enrollment is not configured by the administrator"
        )
    try:
        # Opaque Chrome OAuth access tokens require Google introspection. Never
        # log the request URL, token, upstream body or exception (which may contain it).
        info_response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": token},
            timeout=10,
            allow_redirects=False,
        )
        if info_response.status_code == 429 or info_response.status_code >= 500:
            raise HTTPException(
                503, "Google identity verification is temporarily unavailable"
            )
        if info_response.status_code != 200:
            raise HTTPException(401, "Google identity could not be verified")
        info = info_response.json()
        if not isinstance(info, dict):
            raise ValueError("Invalid token information")
        if (
            info.get("aud") not in clients
            or info.get("azp") not in clients
            or int(info.get("exp", 0)) <= time.time() + 60
        ):
            raise HTTPException(
                401, "Google token has wrong audience or is near expiry"
            )
        scopes = set(info.get("scope", "").split())
        if (
            "https://www.googleapis.com/auth/userinfo.email" not in scopes
            or "openid" not in scopes
        ):
            raise HTTPException(401, "Google token lacks required identity scopes")
        profile_response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            allow_redirects=False,
        )
        if profile_response.status_code == 429 or profile_response.status_code >= 500:
            raise HTTPException(
                503, "Google identity verification is temporarily unavailable"
            )
        if profile_response.status_code != 200:
            raise HTTPException(401, "Google identity could not be verified")
        profile = profile_response.json()
        if not isinstance(profile, dict):
            raise ValueError("Invalid profile")
        email, subject, domain = (
            profile.get("email"),
            profile.get("sub"),
            profile.get("hd"),
        )
        if (
            not isinstance(subject, str)
            or not subject
            or subject != info.get("sub")
            or not isinstance(email, str)
            or len(email) > 320
            or profile.get("email_verified") is not True
        ):
            raise HTTPException(401, "Google identity could not be verified")
        if not isinstance(domain, str) or domain.lower() not in domains:
            raise HTTPException(403, "Workspace domain is not allowed to enroll")
        return {
            "email": email.strip().lower(),
            "sub": subject,
            "hd": domain.lower(),
            "exp": int(info["exp"]),
        }
    except requests.RequestException:
        raise HTTPException(
            503, "Google identity verification is temporarily unavailable"
        ) from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "Google identity could not be verified") from None
