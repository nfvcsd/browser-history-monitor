"""Measured foreground intervals; no durations are inferred from history visits."""
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import String, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..collection import accepts, policy_record
from ..audit import AuditedRoute
from ..auth import require_admin_token, require_extension_token, enforce_device_identity
from ..db import get_db
from ..models import ActivityInterval, Device, User
from ..schemas import SyncBatchIn

sync_router = APIRouter(prefix="/api/v1/sync", tags=["sync"])
router = APIRouter(prefix="/api/v1/activity", tags=["activity"], route_class=AuditedRoute, dependencies=[Depends(require_admin_token)])


class ActivityIn(BaseModel):
    collection_permit: str | None = Field(default=None, max_length=2048)
    sample_id: uuid.UUID
    url: str = Field(min_length=1, max_length=8192)
    title: str | None = Field(default=None, max_length=4096)
    started_at: AwareDatetime
    ended_at: AwareDatetime

    @model_validator(mode="after")
    def valid_interval(self):
        host = urlsplit(self.url).hostname
        if urlsplit(self.url).scheme not in {"http", "https"} or not host or len(host) > 512:
            raise ValueError("Activity requires an HTTP(S) URL with a hostname")
        seconds = (self.ended_at - self.started_at).total_seconds()
        if seconds <= 0 or seconds > 90:
            raise ValueError("Activity intervals must be greater than zero and at most 90 seconds")
        if (self.ended_at - datetime.now(timezone.utc)).total_seconds() > 300:
            raise ValueError("Activity cannot be in the future")
        return self


class ActivityBatchIn(SyncBatchIn):
    intervals: list[ActivityIn] = Field(min_length=1, max_length=250)


@sync_router.post("/activity", dependencies=[Depends(require_extension_token)])
def sync_activity(payload: ActivityBatchIn, request: Request, db: Session = Depends(get_db)):
    enforce_device_identity(request, payload)
    email = str(payload.user_email).strip().lower()
    now = datetime.now(timezone.utc)
    user_id = db.scalar(insert(User).values(email=email, display_name=payload.display_name, last_seen_at=now).on_conflict_do_update(index_elements=[User.email], set_={"last_seen_at": now}).returning(User.id))
    db.execute(insert(Device).values(user_id=user_id, device_key=payload.device_key, device_name=payload.device_name, extension_version=payload.extension_version, last_sync_at=now).on_conflict_do_nothing(index_elements=[Device.device_key]))
    device = db.scalar(select(Device).where(Device.device_key == payload.device_key).with_for_update())
    if device.user_id != user_id:
        raise HTTPException(409, "Device is already enrolled to a different user")
    record = policy_record(db)
    original_count = len(payload.intervals)
    payload.intervals = [item for item in payload.intervals if accepts(record, payload, item, item.started_at, item.ended_at, now)]
    filtered = original_count - len(payload.intervals)
    accepted = 0
    for interval in sorted(payload.intervals, key=lambda item: item.started_at):
        if db.scalar(select(ActivityInterval.id).where(ActivityInterval.device_id == device.id, ActivityInterval.sample_id == interval.sample_id)):
            continue
        overlap = db.scalar(select(ActivityInterval.id).where(ActivityInterval.device_id == device.id, ActivityInterval.started_at < interval.ended_at, ActivityInterval.ended_at > interval.started_at).limit(1))
        if overlap:
            raise HTTPException(422, "Activity intervals on the same device must not overlap")
        db.add(ActivityInterval(user_id=user_id, device_id=device.id, sample_id=interval.sample_id, url=interval.url, title=interval.title, domain=urlsplit(interval.url).hostname.lower(), started_at=interval.started_at, ended_at=interval.ended_at))
        db.flush()
        accepted += 1
    device.last_sync_at = now
    device.last_seen_at = now
    db.commit()
    result = {"accepted": accepted, "duplicates": len(payload.intervals) - accepted}
    if filtered:
        result["filtered"] = filtered
    return result


@router.get("/summary")
def activity_summary(
    group_by: Literal["page", "domain", "user"] = "page",
    user_id: uuid.UUID | None = None,
    domain: str | None = None,
    q: str | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    if start and end and start >= end:
        raise HTTPException(422, "Start must be before end")
    conditions = []
    if user_id:
        conditions.append(ActivityInterval.user_id == user_id)
    if domain and domain.strip():
        conditions.append(ActivityInterval.domain.icontains(domain.strip(), autoescape=True))
    if q and q.strip():
        conditions.append(ActivityInterval.url.icontains(q.strip(), autoescape=True) | ActivityInterval.title.icontains(q.strip(), autoescape=True) | User.email.icontains(q.strip(), autoescape=True))
    left, right = ActivityInterval.started_at, ActivityInterval.ended_at
    if start:
        conditions.append(right > start)
        left = func.greatest(left, start)
    if end:
        conditions.append(ActivityInterval.started_at < end)
        right = func.least(right, end)
    seconds = func.extract("epoch", right - left)
    base = select(ActivityInterval.url, ActivityInterval.title, ActivityInterval.domain, ActivityInterval.user_id, User.email, seconds.label("seconds"), ActivityInterval.started_at).join(User, User.id == ActivityInterval.user_id).where(*conditions).subquery()
    totals = db.execute(select(func.coalesce(func.sum(base.c.seconds), 0).label("active_seconds"), func.count().label("samples"), func.count(distinct(base.c.user_id)).label("users"), func.min(base.c.started_at).label("first_activity"))).mappings().one()
    key = {"page": base.c.url, "domain": base.c.domain, "user": base.c.email}[group_by]
    grouped = select(key.label("key"), func.sum(base.c.seconds).label("active_seconds"), func.count(distinct(base.c.user_id)).label("users"), func.min(base.c.user_id.cast(String)).label("user_id")).group_by(key).subquery()
    if group_by == "page":
        latest = select(base.c.url, base.c.title).distinct(base.c.url).order_by(base.c.url, base.c.started_at.desc()).subquery()
        statement = select(grouped, latest.c.title).join(latest, latest.c.url == grouped.c.key)
    else:
        statement = select(grouped, grouped.c.key.label("title"))
    rows = db.execute(statement.order_by(grouped.c.active_seconds.desc(), grouped.c.key).offset(offset).limit(limit + 1)).mappings().all()
    return {**totals, "items": rows[:limit], "has_more": len(rows) > limit}
