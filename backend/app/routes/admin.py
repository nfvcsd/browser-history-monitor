import uuid
from datetime import datetime, time, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, distinct, func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin_token
from ..db import get_db
from ..models import Device, HistoryVisit, User
from ..schemas import HistoryVisitOut, OverviewOut, UserOut

router = APIRouter(
    prefix="/api/v1",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db)) -> OverviewOut:
    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )

    return OverviewOut(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        devices=db.scalar(select(func.count()).select_from(Device)) or 0,
        visits=db.scalar(select(func.count()).select_from(HistoryVisit)) or 0,
        domains=db.scalar(
            select(func.count(distinct(HistoryVisit.domain))).where(
                HistoryVisit.domain != ""
            )
        )
        or 0,
        visits_today=db.scalar(
            select(func.count()).select_from(HistoryVisit).where(
                HistoryVisit.visit_time >= today_start
            )
        )
        or 0,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.email)))


@router.get("/history", response_model=list[HistoryVisitOut])
def history(
    user_id: uuid.UUID | None = None,
    domain: str | None = None,
    q: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[HistoryVisitOut]:
    stmt = (
        select(HistoryVisit, User.email, Device.device_name)
        .join(User, User.id == HistoryVisit.user_id)
        .join(Device, Device.id == HistoryVisit.device_id)
    )

    if user_id:
        stmt = stmt.where(HistoryVisit.user_id == user_id)
    if domain:
        stmt = stmt.where(HistoryVisit.domain.ilike(f"%{domain.strip()}%"))
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                HistoryVisit.url.ilike(needle),
                HistoryVisit.title.ilike(needle),
                HistoryVisit.domain.ilike(needle),
                cast(User.email, String).ilike(needle),
            )
        )
    if start:
        stmt = stmt.where(HistoryVisit.visit_time >= start)
    if end:
        stmt = stmt.where(HistoryVisit.visit_time <= end)

    rows = db.execute(
        stmt.order_by(HistoryVisit.visit_time.desc()).offset(offset).limit(limit)
    ).all()

    return [
        HistoryVisitOut(
            id=visit.id,
            user_id=visit.user_id,
            user_email=email,
            device_id=visit.device_id,
            device_name=device_name,
            url=visit.url,
            domain=visit.domain,
            title=visit.title,
            visit_time=visit.visit_time,
            transition=visit.transition,
            is_local=visit.is_local,
            visit_count=visit.visit_count,
            typed_count=visit.typed_count,
        )
        for visit, email, device_name in rows
    ]
