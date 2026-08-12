"""Enregistrement des preuves ingerees (quelle que soit la source) dans la base
de donnees et le stockage, avant traitement OCR/video asynchrone."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.applications import Application
from app.models.enums import EvidenceSource, EvidenceType, JobStatus, JobType, ProcessingStatus
from app.models.evidence import EvidenceFile, ProcessingJob
from app.services.ingestion.base import IngestedFile
from app.services.storage.storage_service import get_storage_service, sha256_of_file

settings = get_settings()


def _media_type_for(path: Path) -> EvidenceType:
    ext = path.suffix.lower()
    if ext in settings.allowed_video_extensions:
        return EvidenceType.VIDEO
    if ext in settings.allowed_image_extensions:
        return EvidenceType.IMAGE
    raise ValueError(f"Extension non supportee: {ext}")


def register_evidence(
    db: Session,
    ingested: IngestedFile,
    source: EvidenceSource,
    application_id: str | None = None,
    agent_id: str | None = None,
) -> EvidenceFile:
    storage = get_storage_service()
    media_type = _media_type_for(ingested.source_path)
    file_hash = sha256_of_file(ingested.source_path)

    application_code = "unassigned"
    if application_id:
        application = db.get(Application, application_id)
        if application:
            application_code = application.code

    storage_path = storage.save(ingested.source_path, subdirectory=f"uploads/{application_code}")
    resolved_path = storage.resolve(storage_path)
    mime_type = mimetypes.guess_type(ingested.original_filename)[0] or "application/octet-stream"

    duplicate = db.query(EvidenceFile).filter(EvidenceFile.sha256 == file_hash).first()

    evidence = EvidenceFile(
        original_filename=ingested.original_filename,
        stored_filename=Path(storage_path).name,
        mime_type=mime_type,
        media_type=media_type,
        file_size=resolved_path.stat().st_size,
        sha256=file_hash,
        source=source,
        sender_name=ingested.sender_name,
        sender_phone=ingested.sender_phone,
        whatsapp_message_date=ingested.whatsapp_message_date,
        application_id=application_id,
        agent_id=agent_id,
        processing_status=ProcessingStatus.DUPLICATE if duplicate else ProcessingStatus.PENDING,
        storage_path=storage_path,
        is_duplicate_of_id=duplicate.id if duplicate else None,
    )
    db.add(evidence)
    db.flush()

    # Un doublon (meme SHA-256 qu'une preuve deja enregistree) n'a pas besoin
    # d'etre re-traite par l'OCR : il est deja marque DUPLICATE et reference
    # l'original via is_duplicate_of_id. Pas de ProcessingJob/enqueue pour lui.
    if not duplicate:
        job = ProcessingJob(
            job_type=JobType.VIDEO_ANALYSIS if media_type == EvidenceType.VIDEO else JobType.IMAGE_OCR,
            status=JobStatus.QUEUED,
            related_evidence_id=evidence.id,
        )
        db.add(job)

    return evidence
