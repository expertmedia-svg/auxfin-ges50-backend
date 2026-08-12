from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UUIDMixin
from app.models.enums import EvidenceSource, EvidenceType, JobStatus, JobType, ProcessingStatus, SyncStatus

if TYPE_CHECKING:
    from app.models.applications import Application


class EvidenceFile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_files"

    original_filename: Mapped[str] = mapped_column(String(500))
    stored_filename: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    media_type: Mapped[EvidenceType] = mapped_column(String(20))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[EvidenceSource] = mapped_column(String(30))

    sender_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_message_date: Mapped[datetime | None] = mapped_column(nullable=True)
    received_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    application_detected_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    application_detection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    application_corrected_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    application_corrected_at: Mapped[datetime | None] = mapped_column(nullable=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(String(30), default=ProcessingStatus.PENDING)
    storage_path: Mapped[str] = mapped_column(String(1000))
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_duplicate_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_files.id", ondelete="SET NULL"), nullable=True
    )

    frames: Mapped[list[EvidenceFrame]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan"
    )
    extraction: Mapped[EvidenceExtraction | None] = relationship(
        back_populates="evidence", uselist=False, cascade="all, delete-orphan"
    )
    application: Mapped[Application | None] = relationship(foreign_keys=[application_id])
    application_detected: Mapped[Application | None] = relationship(foreign_keys=[application_detected_id])


class EvidenceFrame(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_frames"

    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id", ondelete="CASCADE"))
    position: Mapped[str] = mapped_column(String(10))  # "start" | "end"
    offset_seconds: Mapped[float] = mapped_column(Float)
    storage_path: Mapped[str] = mapped_column(String(1000))
    is_selected_best: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    evidence: Mapped[EvidenceFile] = relationship(back_populates="frames")
    ocr_results: Mapped[list[OcrResult]] = relationship(
        back_populates="frame", cascade="all, delete-orphan"
    )


class OcrResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ocr_results"

    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id", ondelete="CASCADE"))
    frame_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_frames.id", ondelete="CASCADE"), nullable=True
    )
    engine: Mapped[str] = mapped_column(String(30))
    raw_text: Mapped[str] = mapped_column(String, default="")
    normalized_text: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bounding_boxes: Mapped[list] = mapped_column(JSON, default=list)
    preprocessing_variant: Mapped[str] = mapped_column(String(50), default="default")

    frame: Mapped[EvidenceFrame | None] = relationship(back_populates="ocr_results")


class EvidenceExtraction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_extractions"

    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id", ondelete="CASCADE"), unique=True)

    raw_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    id_correction_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    raw_date: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO yyyy-mm-dd
    date_is_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)

    sync_status: Mapped[SyncStatus] = mapped_column(String(20), default=SyncStatus.UNCONFIRMED)
    sync_status_evidence_text: Mapped[str | None] = mapped_column(String(500), nullable=True)

    application_detected: Mapped[str | None] = mapped_column(String(50), nullable=True)

    confidence_group_id: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_date: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_sync: Mapped[float] = mapped_column(Float, default=0.0)
    global_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    raw_ocr_text: Mapped[str] = mapped_column(String, default="")
    requires_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)

    manually_corrected_group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manually_corrected_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manually_corrected_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    manually_corrected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    correction_history: Mapped[list] = mapped_column(JSON, default=list)

    evidence: Mapped[EvidenceFile] = relationship(back_populates="extraction")

    @property
    def effective_group_id(self) -> str | None:
        return self.manually_corrected_group_id or self.normalized_group_id

    @property
    def effective_date(self) -> str | None:
        return self.manually_corrected_date or self.normalized_date


class ProcessingJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "processing_jobs"

    job_type: Mapped[JobType] = mapped_column(String(30))
    status: Mapped[JobStatus] = mapped_column(String(20), default=JobStatus.PENDING)
    related_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_files.id", ondelete="CASCADE"), nullable=True
    )
    related_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    related_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
