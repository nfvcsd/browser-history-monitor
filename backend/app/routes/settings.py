from datetime import datetime, timedelta, timezone
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..audit import AuditedRoute
from ..auth import require_admin_token, require_extension_token, enforce_device_identity
from ..collection import (
    Policy,
    collection_reason,
    make_permit,
    policy_record,
    source_ip,
)
from ..db import get_db
from ..models import (
    AuditEvent,
    CollectionSettings,
    Device,
    DeviceHealth,
    User,
    DeviceEnrollment,
)
from ..schemas import SyncBatchIn

router = APIRouter(
    prefix="/api/v1/settings", dependencies=[Depends(require_admin_token)]
)
reads = APIRouter(
    prefix="/api/v1/settings",
    dependencies=[Depends(require_admin_token)],
    route_class=AuditedRoute,
)
collection_router = APIRouter(
    prefix="/api/v1/sync", dependencies=[Depends(require_extension_token)]
)


class PolicyUpdate(Policy):
    revision: int = Field(ge=1)


@reads.get("")
def read_settings(db: Session = Depends(get_db)):
    record = policy_record(db)
    db.commit()
    return {**record.policy, "revision": record.revision}


@router.post("")
def save_settings(
    payload: PolicyUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    policy_record(db)
    record = db.scalar(
        select(CollectionSettings)
        .where(CollectionSettings.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.revision != payload.revision:
        raise HTTPException(
            409, "Settings changed in another session. Reload before saving."
        )
    policy = payload.model_dump(exclude={"revision"})
    identity = request.state.admin_identity
    # Save configuration and its audit record atomically: neither can succeed alone.
    db.add(
        AuditEvent(
            actor_sub=identity["sub"],
            actor_email=identity["email"],
            actor_mode=identity["mode"],
            action="settings.update",
            status_code=200,
            filters={"before": record.policy, "after": policy},
            result_count=None,
        )
    )
    record.policy = policy
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {**record.policy, "revision": record.revision}


@reads.get("/devices")
def collection_health(
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    policy = Policy.model_validate(policy_record(db).policy)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=policy.stale_minutes)
    statement = (
        select(Device, User.email, DeviceHealth, DeviceEnrollment)
        .join(User, User.id == Device.user_id)
        .outerjoin(DeviceHealth, DeviceHealth.device_id == Device.id)
        .outerjoin(DeviceEnrollment, DeviceEnrollment.device_id == Device.id)
    )
    if q.strip():
        statement = statement.where(
            User.email.icontains(q.strip(), autoescape=True)
            | Device.device_name.icontains(q.strip(), autoescape=True)
        )
    rows = db.execute(
        statement.order_by(User.email, Device.id).offset(offset).limit(limit + 1)
    ).all()
    items = [
        {
            "id": device.id,
            "email": email,
            "device_name": device.device_name,
            "extension_version": device.extension_version,
            "last_sync_at": device.last_sync_at,
            "last_check_in": health.checked_at if health else None,
            "source_ip": health.source_ip if health else None,
            "enrollment_status": (
                "legacy"
                if not enrollment
                else (
                    "revoked"
                    if enrollment.revoked_at
                    else (
                        "expired"
                        if enrollment.expires_at <= datetime.now(timezone.utc)
                        else "verified"
                    )
                )
            ),
            "verified_at": enrollment.verified_at if enrollment else None,
            "credential_expires_at": enrollment.expires_at if enrollment else None,
            "status": (
                "revoked"
                if enrollment and enrollment.revoked_at
                else (
                    "upgrade_required"
                    if not health
                    else (
                        "not_reporting" if health.checked_at < cutoff else health.reason
                    )
                )
            ),
            "policy_revision": health.policy_revision if health else None,
        }
        for device, email, health, enrollment in rows[:limit]
    ]
    db.commit()
    return {"items": items, "has_more": len(rows) > limit}


class PolicyCheck(SyncBatchIn):
    public_ip: str | None = Field(default=None, max_length=64)


@collection_router.post("/policy")
def check_collection(
    payload: PolicyCheck,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    enforce_device_identity(request,payload)
    now = datetime.now(timezone.utc)
    record = policy_record(db)
    policy = Policy.model_validate(record.policy)
    address = source_ip(request)
    if policy.ip_enabled and policy.ip_source == "device":
        try:
            parsed = ipaddress.ip_address(payload.public_ip or "")
            if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
                parsed = parsed.ipv4_mapped
            address = (
                str(parsed) if parsed.is_global and not parsed.is_multicast else None
            )
        except ValueError:
            address = None
    reason = collection_reason(policy, now, address)
    if policy.ip_enabled and not address:
        reason = "public_ip_unavailable"
    user_id = db.scalar(
        insert(User)
        .values(
            email=str(payload.user_email).lower(),
            display_name=payload.display_name,
            last_seen_at=now,
        )
        .on_conflict_do_update(index_elements=[User.email], set_={"last_seen_at": now})
        .returning(User.id)
    )
    db.execute(
        insert(Device)
        .values(
            user_id=user_id,
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
    if device.user_id != user_id:
        raise HTTPException(409, "Device is already enrolled to a different user")
    device.last_seen_at = now
    device.extension_version = payload.extension_version
    device.device_name = payload.device_name
    health = {
        "device_id": device.id,
        "checked_at": now,
        "reason": reason,
        "source_ip": address,
        "policy_revision": record.revision,
    }
    db.execute(
        insert(DeviceHealth)
        .values(**health)
        .on_conflict_do_update(
            index_elements=[DeviceHealth.device_id],
            set_={key: value for key, value in health.items() if key != "device_id"},
        )
    )
    allowed = reason == "collecting"
    permit, end = (
        make_permit(record, payload, now)
        if allowed
        else (None, now + timedelta(seconds=30))
    )
    result = {
        "allowed": allowed,
        "reason": reason,
        "restricted": policy.schedule_enabled or policy.ip_enabled,
        "ip_source": policy.ip_source,
        "ip_enabled": policy.ip_enabled,
        "source_ip": address,
        "permit": permit,
        "valid_from": now,
        "valid_until": end,
        "revision": record.revision,
    }
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result
