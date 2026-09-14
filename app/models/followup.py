from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin


class EvidenceFollowup(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_followups"

    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id"), unique=True)
    reason: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    send_version: Mapped[int] = mapped_column(Integer, default=0)
    replacement_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_files.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class FollowupMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "followup_messages"

    followup_id: Mapped[str] = mapped_column(ForeignKey("evidence_followups.id"), index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    recipient: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(20), default="SENDING")
    external_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
