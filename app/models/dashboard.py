from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin


class DashboardImport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dashboard_imports"

    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    available_sheets: Mapped[list] = mapped_column(JSON, default=list)
    column_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    uploaded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    missing_columns: Mapped[list] = mapped_column(JSON, default=list)
    error_report: Mapped[list] = mapped_column(JSON, default=list)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    rows: Mapped[list[DashboardImportRow]] = relationship(
        back_populates="dashboard_import", cascade="all, delete-orphan"
    )


class DashboardImportRow(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dashboard_import_rows"

    dashboard_import_id: Mapped[str] = mapped_column(
        ForeignKey("dashboard_imports.id", ondelete="CASCADE")
    )
    row_number: Mapped[int] = mapped_column(Integer)
    raw_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    declared_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sync_date_raw: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sync_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_raw: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extra_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    is_valid: Mapped[bool] = mapped_column(default=True)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    is_duplicate: Mapped[bool] = mapped_column(default=False)

    dashboard_import: Mapped[DashboardImport] = relationship(back_populates="rows")
