import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.models.enums import EvidenceSource, ManualReviewDecision, ProcessingStatus
from app.models.evidence import EvidenceExtraction, EvidenceFile, EvidenceFrame, OcrResult
from app.models.identity import User
from app.models.reconciliation import ManualReview
from app.schemas.evidence import (
    EvidenceCorrection,
    EvidenceExtractionOut,
    EvidenceFrameOut,
    EvidenceOut,
    EvidenceUploadReport,
    ManualReviewDecisionIn,
    OcrResultOut,
)
from app.services.evidence_service import register_evidence
from app.services.ingestion.manual_upload import ManualUploadAdapter, UnsupportedFileError
from app.services.storage.storage_service import get_storage_service

router = APIRouter(prefix="/evidence", tags=["evidence"])
logger = logging.getLogger(__name__)

# Timeout matériel : si le broker Redis est injoignable, kombu peut rester
# bloqué très longtemps sur la connexion malgré la configuration
# broker_connection_retry=False (bug réel constaté en Phase B : une requête
# d'upload est restée bloquée ~2h avant correction de app/workers/celery_app.py,
# puis encore ~110s). Ce garde-fou applicatif garantit que la reponse HTTP
# n'attend jamais l'enqueue plus de quelques secondes, quoi qu'il arrive
# cote broker : la preuve reste QUEUED en base et sera traitee des qu'un
# worker actif sera disponible.
_ENQUEUE_TIMEOUT_SECONDS = 3
_enqueue_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evidence-enqueue")


def _enqueue_processing(evidence_id: str) -> None:
    from app.workers.tasks import process_evidence_task

    def _delay() -> None:
        process_evidence_task.delay(evidence_id)

    future = _enqueue_executor.submit(_delay)
    try:
        future.result(timeout=_ENQUEUE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        logger.warning(
            "Enqueue Celery pour la preuve %s non confirme sous %ss (broker probablement "
            "indisponible) : le traitement reste QUEUED en base, la reponse HTTP n'est pas bloquee.",
            evidence_id, _ENQUEUE_TIMEOUT_SECONDS,
        )
    except Exception:
        # Pas de broker Celery/Redis disponible (ex: environnement de test) :
        # le job reste QUEUED en base et sera traite des qu'un worker sera actif.
        pass


@router.post("/upload", response_model=EvidenceUploadReport, status_code=status.HTTP_201_CREATED)
def upload_evidence(
    files: list[UploadFile] = File(...),
    application_id: str | None = None,
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> EvidenceUploadReport:
    tmp_dir = Path(tempfile.mkdtemp(prefix="ges_g50_upload_"))
    saved_paths: list[str] = []
    for upload in files:
        dest = tmp_dir / upload.filename
        with open(dest, "wb") as f:
            f.write(upload.file.read())
        saved_paths.append(str(dest))

    adapter = ManualUploadAdapter()
    errors: list[str] = []
    evidence_ids: list[str] = []
    to_enqueue: list[str] = []

    try:
        ingested_files = adapter.collect(file_paths=saved_paths)
    except UnsupportedFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    for ingested in ingested_files:
        try:
            evidence = register_evidence(
                db, ingested, EvidenceSource.MANUAL_UPLOAD, application_id=application_id, agent_id=agent_id
            )
            db.flush()
            evidence_ids.append(evidence.id)
            if evidence.processing_status != ProcessingStatus.DUPLICATE:
                to_enqueue.append(evidence.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ingested.original_filename}: {exc}")

    record_audit(
        db, user_id=user.id, action="evidence.upload",
        details={"accepted": len(evidence_ids), "rejected": len(errors)},
    )
    db.commit()

    for evidence_id in to_enqueue:
        _enqueue_processing(evidence_id)

    return EvidenceUploadReport(
        total_files=len(files), accepted=len(evidence_ids), rejected=len(errors),
        errors=errors, evidence_ids=evidence_ids,
    )


@router.get("", response_model=list[EvidenceOut])
def list_evidence(
    application_id: str | None = None,
    processing_status: str | None = None,
    media_type: str | None = None,
    requires_review: bool | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[EvidenceFile]:
    query = db.query(EvidenceFile).options(joinedload(EvidenceFile.extraction))
    if application_id:
        query = query.filter(EvidenceFile.application_id == application_id)
    if processing_status:
        query = query.filter(EvidenceFile.processing_status == processing_status)
    if media_type:
        query = query.filter(EvidenceFile.media_type == media_type)
    if requires_review:
        query = query.filter(EvidenceFile.processing_status == ProcessingStatus.REQUIRES_REVIEW)
    return query.order_by(EvidenceFile.received_at.desc()).offset(offset).limit(limit).all()


@router.get("/{evidence_id}", response_model=EvidenceOut)
def get_evidence(
    evidence_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> EvidenceFile:
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preuve introuvable")
    return evidence


@router.get("/{evidence_id}/media")
def get_evidence_media(
    evidence_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> FileResponse:
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preuve introuvable")
    path = get_storage_service().resolve(evidence.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier introuvable sur le stockage")
    return FileResponse(str(path), media_type=evidence.mime_type, filename=evidence.original_filename)


@router.get("/{evidence_id}/frames", response_model=list[EvidenceFrameOut])
def get_evidence_frames(
    evidence_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[EvidenceFrame]:
    return db.query(EvidenceFrame).filter(EvidenceFrame.evidence_id == evidence_id).order_by(
        EvidenceFrame.position, EvidenceFrame.offset_seconds
    ).all()


@router.get("/frames/{frame_id}/media")
def get_frame_media(
    frame_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> FileResponse:
    frame = db.get(EvidenceFrame, frame_id)
    if frame is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame introuvable")
    path = get_storage_service().resolve(frame.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame introuvable sur le stockage")
    return FileResponse(str(path), media_type="image/jpeg")


@router.post("/frames/{frame_id}/select-best", response_model=EvidenceFrameOut)
def select_best_frame(
    frame_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))
) -> EvidenceFrame:
    frame = db.get(EvidenceFrame, frame_id)
    if frame is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame introuvable")
    db.query(EvidenceFrame).filter(
        EvidenceFrame.evidence_id == frame.evidence_id, EvidenceFrame.position == frame.position
    ).update({"is_selected_best": False})
    frame.is_selected_best = True
    frame.selected_by_user_id = user.id
    record_audit(db, user_id=user.id, action="evidence.select_best_frame", entity_type="evidence_frame", entity_id=frame.id)
    db.commit()
    db.refresh(frame)
    return frame


@router.get("/{evidence_id}/ocr", response_model=list[OcrResultOut])
def get_evidence_ocr(
    evidence_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[OcrResult]:
    return db.query(OcrResult).filter(OcrResult.evidence_id == evidence_id).all()


@router.post("/{evidence_id}/reanalyze", response_model=EvidenceOut)
def reanalyze_evidence(
    evidence_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))
) -> EvidenceFile:
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preuve introuvable")
    evidence.processing_status = ProcessingStatus.QUEUED
    record_audit(db, user_id=user.id, action="evidence.reanalyze", entity_type="evidence_file", entity_id=evidence.id)
    db.commit()
    _enqueue_processing(evidence_id)
    db.refresh(evidence)
    return evidence


@router.patch("/{evidence_id}/correct", response_model=EvidenceExtractionOut)
def correct_evidence(
    evidence_id: str,
    payload: EvidenceCorrection,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> EvidenceExtraction:
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preuve introuvable")
    extraction = evidence.extraction
    if extraction is None:
        extraction = EvidenceExtraction(evidence_id=evidence.id)
        db.add(extraction)

    history_entry = {
        "corrected_by": user.id,
        "corrected_at": datetime.now(UTC).isoformat(),
        "previous_group_id": extraction.effective_group_id,
        "previous_date": extraction.effective_date,
        "new_group_id": payload.group_id,
        "new_date": payload.sync_date,
        "comment": payload.comment,
    }
    extraction.correction_history = [*(extraction.correction_history or []), history_entry]

    if payload.group_id is not None:
        extraction.manually_corrected_group_id = payload.group_id
    if payload.sync_date is not None:
        extraction.manually_corrected_date = payload.sync_date
    extraction.manually_corrected_by_id = user.id
    extraction.manually_corrected_at = datetime.now(UTC)

    if payload.application_id is not None:
        evidence.application_id = payload.application_id
        evidence.application_corrected_by_id = user.id
        evidence.application_corrected_at = datetime.now(UTC)

    if extraction.effective_group_id and extraction.effective_date:
        extraction.requires_manual_review = False
        evidence.processing_status = ProcessingStatus.COMPLETED

    record_audit(
        db, user_id=user.id, action="evidence.correct", entity_type="evidence_file", entity_id=evidence.id,
        details=history_entry,
    )
    db.commit()
    db.refresh(extraction)
    return extraction


@router.post("/{evidence_id}/validate", status_code=status.HTTP_204_NO_CONTENT)
def validate_evidence(
    evidence_id: str,
    payload: ManualReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> None:
    _resolve_manual_review(db, evidence_id, user, ManualReviewDecision.VALIDATED, payload.comment)
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence:
        evidence.processing_status = ProcessingStatus.COMPLETED
    db.commit()


@router.post("/{evidence_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_evidence(
    evidence_id: str,
    payload: ManualReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> None:
    _resolve_manual_review(db, evidence_id, user, ManualReviewDecision.REJECTED, payload.comment)
    db.commit()


def _resolve_manual_review(
    db: Session, evidence_id: str, user: User, decision: ManualReviewDecision, comment: str | None
) -> None:
    review = (
        db.query(ManualReview)
        .filter(ManualReview.evidence_id == evidence_id, ManualReview.decision == ManualReviewDecision.PENDING)
        .first()
    )
    if review is None:
        review = ManualReview(evidence_id=evidence_id, reason="Validation manuelle directe")
        db.add(review)
    review.decision = decision
    review.reviewed_by_id = user.id
    review.reviewed_at = datetime.now(UTC)
    review.comment = comment
    record_audit(
        db, user_id=user.id, action=f"evidence.{decision.value.lower()}",
        entity_type="evidence_file", entity_id=evidence_id,
    )
