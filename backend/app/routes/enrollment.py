import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..auth import require_admin_token
from ..config import get_settings
from ..db import get_db
from ..enrollment import credential_hash, verify_extension_identity
from ..models import AuditEvent, Device, DeviceEnrollment, User

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


class EnrollRequest(BaseModel):
    device_key: str = Field(min_length=8, max_length=64)
    profile_subject: str = Field(min_length=1, max_length=255)
    device_name: str | None = Field(default=None, max_length=255)
    extension_version: str | None = Field(default=None, max_length=40)


@router.post("")
def enroll(
    payload: EnrollRequest,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if get_settings().extension_auth_mode != "enrolled":
        raise HTTPException(403, "Verified enrollment is not enabled on this server")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 16384:
        raise HTTPException(401, "A Google access token is required")
    identity = verify_extension_identity(token)
    if identity["sub"] != payload.profile_subject:
        raise HTTPException(
            403, "Google identity does not match the primary Chrome profile"
        )
    now = datetime.now(timezone.utc)
    db.execute(
        insert(User)
        .values(email=identity["email"], last_seen_at=now)
        .on_conflict_do_nothing(index_elements=[User.email])
    )
    user = db.scalar(
        select(User).where(User.email == identity["email"]).with_for_update()
    )
    if user.google_subject and user.google_subject != identity["sub"]:
        raise HTTPException(
            409, "This email is associated with a different Google identity"
        )
    existing = db.scalar(select(User).where(User.google_subject == identity["sub"]))
    if existing and existing.id != user.id:
        raise HTTPException(
            409, "Google account email changed; administrator review is required"
        )
    user.google_subject = identity["sub"]
    db.execute(
        insert(Device)
        .values(
            user_id=user.id,
            device_key=payload.device_key,
            device_name=payload.device_name,
            extension_version=payload.extension_version,
            last_seen_at=now,
        )
        .on_conflict_do_nothing(index_elements=[Device.device_key])
    )
    device = db.scalar(
        select(Device).where(Device.device_key == payload.device_key).with_for_update()
    )
    if device.user_id != user.id:
        raise HTTPException(409, "Device is enrolled to a different user")
    enrollment = db.get(DeviceEnrollment, device.id)
    if enrollment and enrollment.revoked_at:
        raise HTTPException(403, "Enrollment revoked by administrator")
    secret = secrets.token_urlsafe(32)
    expires = min(
        now + timedelta(hours=1), datetime.fromtimestamp(identity["exp"], timezone.utc)
    )
    first = enrollment is None
    if first:
        enrollment = DeviceEnrollment(
            device_id=device.id,
            google_subject=identity["sub"],
            hosted_domain=identity["hd"],
            credential_hash=credential_hash(secret),
            expires_at=expires,
            verified_at=now,
        )
        db.add(enrollment)
    else:
        if enrollment.google_subject != identity["sub"]:
            raise HTTPException(409, "Enrollment identity mismatch")
        enrollment.credential_hash = credential_hash(secret)
        enrollment.expires_at = expires
        enrollment.verified_at = now
        enrollment.hosted_domain = identity["hd"]
    db.add(
        AuditEvent(
            actor_sub=identity["sub"],
            actor_email=identity["email"],
            actor_mode="google",
            action="device.enroll" if first else "device.renew",
            status_code=200,
            filters={"device_id": str(device.id)},
            result_count=None,
        )
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "device_token": secret,
        "expires_at": expires,
        "device_id": device.id,
        "email": identity["email"],
        "subject": identity["sub"],
    }


@router.post("/{device_id}/revoke", dependencies=[Depends(require_admin_token)])
def revoke_device(
    device_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # Same lock order as enrollment prevents a renewal racing past revocation.
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if not device:
        raise HTTPException(404, "Device not found")
    enrollment = db.get(DeviceEnrollment, device.id)
    if not enrollment:
        raise HTTPException(
            409,
            "Device uses legacy shared credentials; switch to verified enrollment first",
        )
    enrollment.revoked_at = datetime.now(timezone.utc)
    identity = request.state.admin_identity
    db.add(
        AuditEvent(
            actor_sub=identity["sub"],
            actor_email=identity["email"],
            actor_mode=identity["mode"],
            action="device.revoke",
            status_code=200,
            filters={"device_id": str(device.id)},
            result_count=None,
        )
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"revoked": True}
