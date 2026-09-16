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
from sqlalchemy.dialects.postgresql import UUID
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
