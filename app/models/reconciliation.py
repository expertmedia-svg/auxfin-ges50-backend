from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin
from app.models.enums import ManualReviewDecision, ReconciliationStatus


class ReconciliationRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_runs"

    dashboard_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("dashboard_imports.id", ondelete="SET NULL"), nullable=True
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    date_tolerance_days: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    triggered_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    results: Mapped[list[ReconciliationResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ReconciliationResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_results"

    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="CASCADE"))
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ReconciliationStatus] = mapped_column(String(50), index=True)

    whatsapp_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dashboard_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    whatsapp_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dashboard_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_files.id", ondelete="SET NULL"), nullable=True
    )
    dashboard_import_row_id: Mapped[str | None] = mapped_column(
        ForeignKey("dashboard_import_rows.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.0)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_action: Mapped[str | None] = mapped_column(String(200), nullable=True)

    run: Mapped[ReconciliationRun] = relationship(back_populates="results")


class ManualReview(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "manual_reviews"

    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id", ondelete="CASCADE"))
    reconciliation_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("reconciliation_results.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(300))
    decision: Mapped[ManualReviewDecision] = mapped_column(String(20), default=ManualReviewDecision.PENDING)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
