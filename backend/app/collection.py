"""Collection policy, source-address verification and bounded retention cleanup."""

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from .config import get_settings
from .models import ActivityInterval, CollectionSettings, HistoryVisit


class DayWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    start: str = "08:00"
    end: str = "16:00"

    @field_validator("start", "end")
    @classmethod
    def time_format(cls, value):
        import re

        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Use HH:MM in 24-hour time")
        return value

    @model_validator(mode="after")
    def not_equal(self):
        if self.enabled and self.start == self.end:
            raise ValueError(
                "Start and end must differ; disable scheduling for all-day collection"
            )
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    stale_minutes: int = Field(default=15, ge=2, le=10080)
    timezone: str = "America/Chicago"
    schedule_enabled: bool = False
    days: list[DayWindow] = Field(
        default_factory=lambda: [DayWindow() for _ in range(7)],
        min_length=7,
        max_length=7,
    )
    ip_source: Literal["connection", "device"] = "connection"
    ip_enabled: bool = False
    public_ips: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose an IANA timezone, for example America/Chicago")
        return value

    @field_validator("public_ips")
    @classmethod
    def valid_ips(cls, values):
        result = []
        for value in values:
            address = ipaddress.ip_address(value.strip())
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_global or address.is_multicast:
                raise ValueError(
                    "Only individual public IPv4/IPv6 addresses are allowed"
                )
            result.append(str(address))
        return sorted(set(result))


def policy_record(db):
    db.execute(
        insert(CollectionSettings)
        .values(
            id=1,
            revision=1,
            policy=Policy().model_dump(),
            signing_key=secrets.token_hex(32),
        )
        .on_conflict_do_nothing(index_elements=[CollectionSettings.id])
    )
    return db.get(CollectionSettings, 1)


def utc(value):
    # Legacy history clients may send naive timestamps; those have always meant UTC.
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def scheduled(policy, at):
    if not policy.schedule_enabled:
        return True
    local = utc(at).astimezone(ZoneInfo(policy.timezone))
    minute = local.strftime("%H:%M")
    today = policy.days[local.weekday()]
    yesterday = policy.days[(local.weekday() - 1) % 7]
    # Overnight windows belong to their starting weekday, including Sunday -> Monday.
    return bool(
        (
            today.enabled
            and (
                (today.start < today.end and today.start <= minute < today.end)
                or (today.start > today.end and minute >= today.start)
            )
        )
        or (
            yesterday.enabled
            and yesterday.start > yesterday.end
            and minute < yesterday.end
        )
    )


def source_ip(request: Request):
    """Ignore forwarded headers unless the TCP peer is an explicitly trusted proxy."""
    try:
        peer = ipaddress.ip_address(request.client.host)
        trusted = [
            ipaddress.ip_network(value.strip())
            for value in get_settings().trusted_proxy_cidrs.split(",")
            if value.strip()
        ]

        def is_trusted(address):
            return any(address in network for network in trusted)

        if is_trusted(peer):
            chain = request.headers.get("x-forwarded-for", "").split(",")
            if len(chain) > 20 or not chain[0].strip():
                return None
            for value in reversed(chain):
                peer = ipaddress.ip_address(value.strip())
                if not is_trusted(peer):
                    break
        if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        return str(peer)
    except (ValueError, AttributeError):
        return None


def collection_reason(policy, now, address):
    if not scheduled(policy, now):
        return "outside_schedule"
    if policy.ip_enabled and address not in policy.public_ips:
        return "ip_not_allowed"
    return "collecting"


def make_permit(record, payload, now):
    policy = Policy.model_validate(record.policy)
    end = now + timedelta(seconds=45)
    # Never authorize across a schedule boundary, including a DST transition.
    probe = now.replace(microsecond=0) + timedelta(seconds=1)
    while probe < end:
        if not scheduled(policy, probe):
            end = probe
            break
        probe += timedelta(seconds=1)
    data = {
        "revision": record.revision,
        "email": str(payload.user_email).lower(),
        "device": payload.device_key,
        "start": now.timestamp(),
        "end": end.timestamp(),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode()
    signature = hmac.new(
        record.signing_key.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return body + "." + signature, end


def accepts(record, payload, item, start, end=None, now=None):
    policy = Policy.model_validate(record.policy)
    now = now or datetime.now(timezone.utc)
    start, end = utc(start), utc(end or start)
    if start > now + timedelta(seconds=300):
        return False
    if policy.retention_days and start < now - timedelta(days=policy.retention_days):
        return False
    if not (policy.schedule_enabled or policy.ip_enabled):
        return True
    try:
        body, signature = (item.collection_permit or "").split(".")
        expected = hmac.new(
            record.signing_key.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        data = json.loads(base64.urlsafe_b64decode(body))
        return (
            data["revision"] == record.revision
            and data["email"] == str(payload.user_email).lower()
            and data["device"] == payload.device_key
            and data["start"] <= start.timestamp() < data["end"]
            and end.timestamp() <= data["end"]
        )
    except (ValueError, KeyError, TypeError):
        return False


def cleanup_retention(db, now=None, batch_size=10000):
    """Bound each pass; run periodically. Never delete users, devices or audit events."""
    policy_record(db)
    # Serialize cleanup with settings edits and other backend workers. A completed
    # settings save cannot be followed by cleanup using the previous policy.
    record = db.scalar(select(CollectionSettings).where(CollectionSettings.id == 1).with_for_update().execution_options(populate_existing=True))
    policy = Policy.model_validate(record.policy)
    if not policy.retention_days:
        db.commit()
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=policy.retention_days)
    total = 0
    for model, column in [
        (HistoryVisit, HistoryVisit.visit_time),
        (ActivityInterval, ActivityInterval.ended_at),
    ]:
        ids = (
            select(model.id).where(column < cutoff if model is HistoryVisit else column <= cutoff).order_by(model.id).limit(batch_size)
        )
        total += db.execute(delete(model).where(model.id.in_(ids))).rowcount
    db.execute(
        update(ActivityInterval)
        .where(
            ActivityInterval.started_at < cutoff, ActivityInterval.ended_at >= cutoff
        )
        .values(started_at=cutoff)
    )
    db.commit()
    return total
