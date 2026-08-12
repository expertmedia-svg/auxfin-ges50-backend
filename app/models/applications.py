from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin
from app.models.enums import EvidenceType


class Application(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped[ApplicationProfile | None] = relationship(
        back_populates="application", uselist=False, cascade="all, delete-orphan"
    )


class ApplicationProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "application_profiles"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True
    )
    expected_evidence_type: Mapped[EvidenceType] = mapped_column(
        String(20), default=EvidenceType.VIDEO
    )
    id_regex: Mapped[str] = mapped_column(String(300), default=r"gr\d+\.[a-z0-9\-]+")
    screen_zones: Mapped[dict] = mapped_column(JSON, default=dict)
    success_keywords: Mapped[list] = mapped_column(JSON, default=list)
    error_keywords: Mapped[list] = mapped_column(JSON, default=list)
    date_format_hints: Mapped[list] = mapped_column(JSON, default=list)
    logo_keywords: Mapped[list] = mapped_column(JSON, default=list)
    primary_color_hint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    video_start_offsets_seconds: Mapped[list | None] = mapped_column(JSON, nullable=True)
    video_end_offsets_seconds: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    application: Mapped[Application] = relationship(back_populates="profile")


class Agent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    full_name: Mapped[str] = mapped_column(String(200))
    whatsapp_phone: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    whatsapp_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(150), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    group_assignments: Mapped[list[AgentGroupAssignment]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentGroupAssignment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agent_group_assignments"
    __table_args__ = (UniqueConstraint("agent_id", "application_id", "group_id"),)

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    group_id: Mapped[str] = mapped_column(String(150), index=True)

    agent: Mapped[Agent] = relationship(back_populates="group_assignments")
    application: Mapped[Application] = relationship()
