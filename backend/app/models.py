import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    devices: Mapped[list["Device"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extension_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="devices")
    visits: Mapped[list["HistoryVisit"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class HistoryVisit(Base):
    __tablename__ = "history_visits"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "chrome_visit_id", name="uq_history_visit_device_chrome_visit"
        ),
        Index("ix_history_visits_user_time", "user_id", "visit_time"),
        Index("ix_history_visits_domain_time", "domain", "visit_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )

    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    visit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    chrome_visit_id: Mapped[str] = mapped_column(String(128))
    chrome_history_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    referring_visit_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_local: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    visit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    typed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    device: Mapped["Device"] = relationship(back_populates="visits")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_actor_time", "actor_email", "created_at"),
        Index("ix_audit_action_time", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_sub: Mapped[str] = mapped_column(String(255))
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    actor_mode: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    filters: Mapped[dict] = mapped_column(JSONB)
    result_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ActivityInterval(Base):
    __tablename__ = "activity_intervals"
    __table_args__ = (
        UniqueConstraint("device_id", "sample_id", name="uq_activity_device_sample"),
        Index("ix_activity_user_start", "user_id", "started_at"),
        Index("ix_activity_domain_start", "domain", "started_at"),
        Index("ix_activity_device_start", "device_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"))
    sample_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(512))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
