from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_extension_token
from ..db import get_db
from ..models import Device, HistoryVisit, User
from ..schemas import SyncBatchIn, SyncBatchOut

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


def extract_domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


@router.post(
    "/batch",
    response_model=SyncBatchOut,
    dependencies=[Depends(require_extension_token)],
)
def sync_batch(payload: SyncBatchIn, db: Session = Depends(get_db)) -> SyncBatchOut:
    now = datetime.now(timezone.utc)
    email = str(payload.user_email).strip().lower()

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=payload.display_name, last_seen_at=now)
        db.add(user)
        db.flush()
    else:
        if payload.display_name and not user.display_name:
            user.display_name = payload.display_name
        user.last_seen_at = now

    device = db.scalar(select(Device).where(Device.device_key == payload.device_key))
    if device is None:
        device = Device(
            user_id=user.id,
            device_key=payload.device_key,
            device_name=payload.device_name,
            extension_version=payload.extension_version,
            last_seen_at=now,
            last_sync_at=now,
        )
        db.add(device)
        db.flush()
    else:
        # A device changing users unexpectedly should not silently rewrite ownership.
        if device.user_id != user.id:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device is already enrolled to a different user",
            )
        device.device_name = payload.device_name or device.device_name
        device.extension_version = payload.extension_version or device.extension_version
        device.last_seen_at = now
        device.last_sync_at = now

    accepted = 0
    duplicates = 0

    for visit in payload.visits:
        exists = db.scalar(
            select(HistoryVisit.id).where(
                HistoryVisit.device_id == device.id,
                HistoryVisit.chrome_visit_id == visit.chrome_visit_id,
            )
        )
        if exists is not None:
            duplicates += 1
            continue

        db.add(
            HistoryVisit(
                user_id=user.id,
                device_id=device.id,
                url=visit.url,
                domain=extract_domain(visit.url),
                title=visit.title,
                visit_time=visit.visit_time,
                chrome_visit_id=visit.chrome_visit_id,
                chrome_history_id=visit.chrome_history_id,
                referring_visit_id=visit.referring_visit_id,
                transition=visit.transition,
                is_local=visit.is_local,
                visit_count=visit.visit_count,
                typed_count=visit.typed_count,
            )
        )
        accepted += 1

    try:
        db.commit()
    except IntegrityError:
        # This protects against concurrent duplicate submissions.
        db.rollback()
        # Re-run conservatively one-by-one if a race occurred.
        accepted = 0
        duplicates = 0
        user = db.scalar(select(User).where(User.email == email))
        device = db.scalar(select(Device).where(Device.device_key == payload.device_key))
        for visit in payload.visits:
            exists = db.scalar(
                select(HistoryVisit.id).where(
                    HistoryVisit.device_id == device.id,
                    HistoryVisit.chrome_visit_id == visit.chrome_visit_id,
                )
            )
            if exists is not None:
                duplicates += 1
                continue
            db.add(
                HistoryVisit(
                    user_id=user.id,
                    device_id=device.id,
                    url=visit.url,
                    domain=extract_domain(visit.url),
                    title=visit.title,
                    visit_time=visit.visit_time,
                    chrome_visit_id=visit.chrome_visit_id,
                    chrome_history_id=visit.chrome_history_id,
                    referring_visit_id=visit.referring_visit_id,
                    transition=visit.transition,
                    is_local=visit.is_local,
                    visit_count=visit.visit_count,
                    typed_count=visit.typed_count,
                )
            )
            try:
                db.commit()
                accepted += 1
            except IntegrityError:
                db.rollback()
                duplicates += 1

    return SyncBatchOut(
        accepted=accepted,
        duplicates=duplicates,
        user_id=user.id,
        device_id=device.id,
        server_time=now,
    )
