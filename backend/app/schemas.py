import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


class VisitIn(BaseModel):
    chrome_visit_id: str = Field(min_length=1, max_length=128)
    chrome_history_id: str | None = Field(default=None, max_length=128)
    referring_visit_id: str | None = Field(default=None, max_length=128)
    url: str = Field(min_length=1)
    title: str | None = None
    visit_time: datetime
    transition: str | None = Field(default=None, max_length=64)
    is_local: bool | None = None
    visit_count: int | None = None
    typed_count: int | None = None


class SyncBatchIn(BaseModel):
    user_email: EmailStr
    display_name: str | None = None
    device_key: str = Field(min_length=8, max_length=64)
    device_name: str | None = Field(default=None, max_length=255)
    extension_version: str | None = Field(default=None, max_length=40)
    visits: list[VisitIn] = Field(default_factory=list, max_length=1000)


class SyncBatchOut(BaseModel):
    accepted: int
    duplicates: int
    user_id: uuid.UUID
    device_id: uuid.UUID
    server_time: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    last_seen_at: datetime


class HistoryVisitOut(BaseModel):
    id: int
    user_id: uuid.UUID
    user_email: str
    device_id: uuid.UUID
    device_name: str | None
    url: str
    domain: str
    title: str | None
    visit_time: datetime
    transition: str | None
    is_local: bool | None
    visit_count: int | None
    typed_count: int | None


class OverviewOut(BaseModel):
    users: int
    devices: int
    visits: int
    domains: int
    visits_today: int


class UserSummaryOut(UserOut):
    last_sync_at: datetime | None
    device_count: int
    visit_count: int


class DomainOut(BaseModel):
    domain: str
    visit_count: int
    unique_users: int
    first_activity: datetime
    last_activity: datetime


class ReportDomainOut(BaseModel):
    domain: str
    visit_count: int
    unique_users: int


class ReportDayOut(BaseModel):
    date: date
    visits: int


class ReportHourOut(BaseModel):
    hour: int
    visits: int


class ReportOut(BaseModel):
    start: date
    end: date
    timezone: str
    visits: int
    users: int
    devices: int
    domains: int
    top_domains: list[ReportDomainOut]
    daily: list[ReportDayOut]
    hourly: list[ReportHourOut]
