from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import ACTIONS, AuditedRoute
from ..auth import require_admin_token
from ..db import get_db
from ..models import AuditEvent
from ..schemas import AuditPageOut

router = APIRouter(
    prefix="/api/v1",
    tags=["audit"],
    route_class=AuditedRoute,
    dependencies=[Depends(require_admin_token)],
)


@router.get("/audit", response_model=AuditPageOut)
def audit_log(
    actor: Annotated[str | None, Query(max_length=320)] = None,
    action: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    db: Session = Depends(get_db),
):
    if action and action not in {*ACTIONS.values(), "history.search"}:
        raise HTTPException(422, "Unknown audit action")
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start and end and start > end:
        raise HTTPException(422, "Start must be before end")
    stmt = select(AuditEvent)
    if actor and actor.strip():
        needle = actor.strip()
        stmt = stmt.where(
            or_(
                AuditEvent.actor_email.icontains(needle, autoescape=True),
                AuditEvent.actor_sub.icontains(needle, autoescape=True),
            )
        )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if start:
        stmt = stmt.where(AuditEvent.created_at >= start)
    if end:
        stmt = stmt.where(AuditEvent.created_at <= end)
    if before_id:
        stmt = stmt.where(AuditEvent.id < before_id)
    rows = list(db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit + 1)))
    return {
        "items": rows[:limit],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }
