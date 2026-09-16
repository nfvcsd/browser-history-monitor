import uuid
from datetime import datetime, time, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, distinct, func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin_token
from ..audit import AuditedRoute
from ..db import get_db
from ..models import Device, HistoryVisit, User
from ..timezones import report_timezone
from ..schemas import DomainOut, HistoryVisitOut, OverviewOut, UserOut, UserSummaryOut

router = APIRouter(
    route_class=AuditedRoute,
    prefix="/api/v1",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/overview", response_model=OverviewOut)
def overview(
    timezone_name: Annotated[str, Query(alias="timezone", max_length=100)] = "UTC",
    db: Session = Depends(get_db),
) -> OverviewOut:
    zone = report_timezone(timezone_name)
    today_start = datetime.combine(
        datetime.now(zone).date(), time.min, tzinfo=zone
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


def user_summary_statement():
    # Aggregate independently to avoid multiplying visits by the number of devices.
    devices = select(
        Device.user_id,
        func.count().label("device_count"),
        func.max(Device.last_sync_at).label("last_sync_at"),
    ).group_by(Device.user_id).subquery()
    visits = select(
        HistoryVisit.user_id, func.count().label("visit_count")
    ).group_by(HistoryVisit.user_id).subquery()
    return select(
        *User.__table__.columns,
        func.coalesce(devices.c.device_count, 0).label("device_count"),
        devices.c.last_sync_at,
        func.coalesce(visits.c.visit_count, 0).label("visit_count"),
    ).outerjoin(devices, devices.c.user_id == User.id).outerjoin(
        visits, visits.c.user_id == User.id
    )


@router.get("/users/summary", response_model=list[UserSummaryOut])
def user_summaries(
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    stmt = user_summary_statement()
    if q and q.strip():
        stmt = stmt.where(or_(
            User.email.icontains(q.strip(), autoescape=True),
            User.display_name.icontains(q.strip(), autoescape=True),
        ))
    return db.execute(stmt.order_by(User.email, User.id).offset(offset).limit(limit)).mappings().all()


@router.get("/users/{user_id}", response_model=UserSummaryOut)
def user_detail(user_id: uuid.UUID, db: Session = Depends(get_db)):
    row = db.execute(user_summary_statement().where(User.id == user_id)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.get("/domains", response_model=list[DomainOut])
def domains(
    q: str | None = None,
    user_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    if start and end and start.timestamp() > end.timestamp():
        raise HTTPException(status_code=422, detail="Start must be before end")
    stmt = select(
        HistoryVisit.domain,
        func.count().label("visit_count"),
        func.count(distinct(HistoryVisit.user_id)).label("unique_users"),
        func.min(HistoryVisit.visit_time).label("first_activity"),
        func.max(HistoryVisit.visit_time).label("last_activity"),
    ).where(HistoryVisit.domain != "")
    if q and q.strip():
        stmt = stmt.where(HistoryVisit.domain.icontains(q.strip(), autoescape=True))
    if user_id:
        stmt = stmt.where(HistoryVisit.user_id == user_id)
    if start:
        stmt = stmt.where(HistoryVisit.visit_time >= start)
    if end:
        stmt = stmt.where(HistoryVisit.visit_time <= end)
    return db.execute(stmt.group_by(HistoryVisit.domain).order_by(
        func.count().desc(), HistoryVisit.domain
    ).offset(offset).limit(limit)).mappings().all()


@router.get("/history", response_model=list[HistoryVisitOut])
def history(
    user_id: uuid.UUID | None = None,
    domain: str | None = None,
    exact_domain: str | None = None,
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
    if exact_domain is not None:
        stmt = stmt.where(HistoryVisit.domain == exact_domain.strip().lower())
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
        stmt.order_by(HistoryVisit.visit_time.desc(), HistoryVisit.id.desc()).offset(offset).limit(limit)
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
