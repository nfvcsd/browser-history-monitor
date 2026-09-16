"""Report aggregation and CSV export share the same inclusive UTC date filters."""

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ..auth import require_admin_token
from ..db import SessionLocal, get_db
from ..models import Device, HistoryVisit, User
from ..schemas import ReportOut

router = APIRouter(
    prefix="/api/v1/reports",
    tags=["reports"],
    dependencies=[Depends(require_admin_token)],
)


class ReportFilters:
    def __init__(
        self,
        start: date,
        end: date,
        user_id: uuid.UUID | None = None,
        domain: Annotated[str | None, Query(max_length=512)] = None,
    ):
        if end < start or (end - start).days >= 366 or end == date.max:
            raise HTTPException(
                422, "Choose a date range of 1–366 days, with start on or before end"
            )
        self.start, self.end = start, end
        self.conditions = [
            HistoryVisit.visit_time >= datetime.combine(start, time.min, timezone.utc),
            HistoryVisit.visit_time
            < datetime.combine(end + timedelta(days=1), time.min, timezone.utc),
        ]
        if user_id:
            self.conditions.append(HistoryVisit.user_id == user_id)
        if domain and domain.strip():
            self.conditions.append(
                HistoryVisit.domain.icontains(domain.strip(), autoescape=True)
            )


@router.get("", response_model=ReportOut)
def report(filters: ReportFilters = Depends(), db: Session = Depends(get_db)):
    summary = (
        db.execute(
            select(
                func.count().label("visits"),
                func.count(distinct(HistoryVisit.user_id)).label("users"),
                func.count(distinct(HistoryVisit.device_id)).label("devices"),
                func.count(distinct(HistoryVisit.domain))
                .filter(HistoryVisit.domain != "")
                .label("domains"),
            ).where(*filters.conditions)
        )
        .mappings()
        .one()
    )
    top = (
        db.execute(
            select(
                HistoryVisit.domain,
                func.count().label("visit_count"),
                func.count(distinct(HistoryVisit.user_id)).label("unique_users"),
            )
            .where(*filters.conditions, HistoryVisit.domain != "")
            .group_by(HistoryVisit.domain)
            .order_by(func.count().desc(), HistoryVisit.domain)
            .limit(20)
        )
        .mappings()
        .all()
    )
    utc_time = func.timezone("UTC", HistoryVisit.visit_time)
    day = func.date(utc_time)
    hour = func.extract("hour", utc_time)
    daily = dict(
        db.execute(
            select(day, func.count()).where(*filters.conditions).group_by(day)
        ).all()
    )
    hourly = dict(
        db.execute(
            select(hour, func.count()).where(*filters.conditions).group_by(hour)
        ).all()
    )
    return {
        "start": filters.start,
        "end": filters.end,
        "timezone": "UTC",
        **summary,
        "top_domains": top,
        "daily": [
            {
                "date": filters.start + timedelta(days=i),
                "visits": daily.get(filters.start + timedelta(days=i), 0),
            }
            for i in range((filters.end - filters.start).days + 1)
        ],
        "hourly": [{"hour": i, "visits": hourly.get(i, 0)} for i in range(24)],
    }


def csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    # Spreadsheet applications must not execute titles/URLs/device names as formulas.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


@router.get("/export.csv")
def export_report(filters: ReportFilters = Depends()):
    def rows():
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)

        def encode(values):
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([csv_cell(value) for value in values])
            return buffer.getvalue()

        yield encode(
            [
                "visit_id",
                "visit_time_utc",
                "user_email",
                "device_name",
                "domain",
                "url",
                "title",
                "transition",
            ]
        )
        # Own the session for the complete stream, including client disconnect cleanup.
        with SessionLocal() as db:
            statement = (
                select(
                    HistoryVisit.id,
                    HistoryVisit.visit_time,
                    User.email,
                    Device.device_name,
                    HistoryVisit.domain,
                    HistoryVisit.url,
                    HistoryVisit.title,
                    HistoryVisit.transition,
                )
                .join(User, User.id == HistoryVisit.user_id)
                .join(Device, Device.id == HistoryVisit.device_id)
                .where(*filters.conditions)
                .order_by(HistoryVisit.visit_time, HistoryVisit.id)
                .execution_options(yield_per=1000)
            )
            for row in db.execute(statement):
                yield encode(
                    [row[0], row[1].astimezone(timezone.utc).isoformat(), *row[2:]]
                )

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="history-{filters.start}-{filters.end}.csv"',
            "Cache-Control": "no-store",
        },
    )
