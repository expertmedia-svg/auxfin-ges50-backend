from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin
from app.models.enums import WhatsAppConnectionState, WhatsAppDownloadStatus, WhatsAppMessageType

if TYPE_CHECKING:
    from app.models.applications import Application
    from app.models.evidence import EvidenceFile
    from app.models.identity import User


class WhatsAppGroup(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_groups"

    whatsapp_group_external_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=False)

    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    supervisor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    zone_label: Mapped[str | None] = mapped_column(String(150), nullable=True)

    last_activity_at: Mapped[datetime | None] = mapped_column(nullable=True)

    application: Mapped[Application | None] = relationship()
    supervisor: Mapped[User | None] = relationship()
    messages: Mapped[list[WhatsAppMessage]] = relationship(back_populates="group")


class WhatsAppMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_messages"

    whatsapp_message_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("whatsapp_groups.id", ondelete="SET NULL"), nullable=True
    )
    group_external_id: Mapped[str] = mapped_column(String(150), index=True)

    sender_external_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    message_date: Mapped[datetime] = mapped_column()
    message_type: Mapped[WhatsAppMessageType] = mapped_column(String(20), default=WhatsAppMessageType.OTHER)
    caption_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    media_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    media_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    download_status: Mapped[WhatsAppDownloadStatus] = mapped_column(
        String(30), default=WhatsAppDownloadStatus.PENDING
    )
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_files.id", ondelete="SET NULL"), nullable=True
    )

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duplicate_of_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("whatsapp_messages.id", ondelete="SET NULL"), nullable=True
    )

    group: Mapped[WhatsAppGroup | None] = relationship(back_populates="messages")
    evidence: Mapped[EvidenceFile | None] = relationship()


class WhatsAppGatewayStatus(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_gateway_status"

    connection_state: Mapped[WhatsAppConnectionState] = mapped_column(
        String(20), default=WhatsAppConnectionState.DISCONNECTED
    )
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(nullable=True)
