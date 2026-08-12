"""Traitement complet d'une preuve : OCR/video, normalisation ID/date, statut
de synchronisation, identification de l'application si necessaire, et
persistance des resultats (evidence_frames, ocr_results, evidence_extractions,
manual_reviews). Utilise a la fois par les taches Celery et par les scripts de
verification manuelle, pour ne pas dupliquer la logique."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.applications import Application, ApplicationProfile
from app.models.dashboard import DashboardImportRow
from app.models.enums import EvidenceType, JobStatus, ProcessingStatus, SyncStatus
from app.models.evidence import EvidenceExtraction, EvidenceFile, EvidenceFrame, OcrResult, ProcessingJob
from app.models.reconciliation import ManualReview
from app.services.vision.application_detector import detect_application
from app.services.vision.extraction_pipeline import (
    ExtractionOutcome,
    extract_from_image,
    extract_from_video,
)
from app.services.vision.status_icon import detect_status_icon_color
from app.services.vision.sync_status import detect_sync_status

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_SUCCESS_KEYWORDS = [
    "synchronisation reussie", "synchronise", "donnees synchronisees",
    "synchronisation terminee", "termine", "succes", "success", "completed",
    "upload complete", "donnees envoyees",
]
DEFAULT_ERROR_KEYWORDS = [
    "echec", "erreur", "connexion impossible", "synchronisation echouee",
    "failed", "error", "timeout", "donnees non envoyees",
]


def _known_ids_for(db: Session, application_id: str | None) -> list[str]:
    query = db.query(DashboardImportRow.normalized_group_id).filter(
        DashboardImportRow.normalized_group_id.isnot(None)
    )
    if application_id:
        query = query.join(DashboardImportRow.dashboard_import).filter(
            DashboardImportRow.dashboard_import.has(application_id=application_id)
        )
    return [row[0] for row in query.distinct().limit(5000).all()]


def _context_date(evidence: EvidenceFile) -> datetime | None:
    if evidence.whatsapp_message_date:
        return evidence.whatsapp_message_date
    return evidence.received_at


def process_evidence(db: Session, evidence_id: str) -> EvidenceFile:
    evidence = db.get(EvidenceFile, evidence_id)
    if evidence is None:
        raise ValueError(f"Preuve introuvable: {evidence_id}")

    job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.related_evidence_id == evidence_id)
        .order_by(ProcessingJob.created_at.desc())
        .first()
    )
    started_at = time.monotonic()
    if job:
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        job.attempts += 1

    evidence.processing_status = ProcessingStatus.PROCESSING
    # Commit (pas juste flush) avant le pipeline OCR/video : sous SQLite,
    # laisser une transaction ouverte pendant les dizaines de secondes que
    # peut prendre le traitement d'une video bloque tout autre ecrivain
    # (ex: mise a jour de last_login_at au login) avec une erreur reelle
    # "database is locked" au-dela du busy_timeout — constate en testant le
    # worker natif de bout en bout (Phase C). _run_pipeline ne fait que des
    # lectures DB, donc valider ce commit tot est sans risque de coherence.
    db.commit()

    try:
        outcome, resolved_app = _run_pipeline(db, evidence)
        _persist_outcome(db, evidence, outcome, resolved_app)

        evidence.processing_status = (
            ProcessingStatus.REQUIRES_REVIEW if outcome.requires_manual_review else ProcessingStatus.COMPLETED
        )
        if job:
            job.status = JobStatus.COMPLETED
            job.result_summary = {
                "normalized_group_id": outcome.normalized_group_id,
                "normalized_date": outcome.normalized_date,
                "sync_status": outcome.sync_status.value,
                "requires_manual_review": outcome.requires_manual_review,
            }
    except Exception as exc:  # noqa: BLE001 - on consigne l'erreur reelle, jamais de faux succes
        logger.exception("Echec du traitement de la preuve %s", evidence_id)
        evidence.processing_status = ProcessingStatus.FAILED
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
    finally:
        if job:
            job.finished_at = datetime.now(UTC)
            job.duration_ms = int((time.monotonic() - started_at) * 1000)

    db.commit()
    db.refresh(evidence)
    return evidence


def _run_pipeline(db: Session, evidence: EvidenceFile) -> tuple[ExtractionOutcome, Application | None]:
    context_date = _context_date(evidence)
    context_date_only = context_date.date() if context_date else None
    resolved_path = str(_resolve_storage_path(evidence))

    application = db.get(Application, evidence.application_id) if evidence.application_id else None
    profile = application.profile if application else None

    if profile is not None:
        known_ids = _known_ids_for(db, application.id)
        outcome = _extract(evidence, resolved_path, profile, known_ids, context_date_only)
        return outcome, application

    # Mode automatique : premiere passe avec des mots-cles generiques (union de
    # tous les profils actifs), puis identification de l'application depuis le
    # texte OCR obtenu, sans jamais re-decoder la video.
    all_profiles = (
        db.query(ApplicationProfile)
        .join(ApplicationProfile.application)
        .filter(Application.is_active.is_(True))
        .all()
    )
    generic_success = list({kw for p in all_profiles for kw in p.success_keywords} | set(DEFAULT_SUCCESS_KEYWORDS))
    generic_error = list({kw for p in all_profiles for kw in p.error_keywords} | set(DEFAULT_ERROR_KEYWORDS))

    outcome = _extract_generic(evidence, resolved_path, generic_success, generic_error, context_date_only)

    detection = detect_application(
        outcome.raw_ocr_text,
        [(p.application.id, p.application.code, p.application.name, p.logo_keywords) for p in all_profiles],
    )
    evidence.application_detection_confidence = detection.confidence

    if detection.application_id:
        evidence.application_detected_id = detection.application_id
        matched_profile = next(p for p in all_profiles if p.application_id == detection.application_id)
        # Rafine le statut de synchronisation avec les mots-cles specifiques de
        # l'application detectee, sans nouvelle extraction video/OCR.
        end_text_source = outcome.raw_ocr_text
        status_result = detect_sync_status(
            end_text_source, matched_profile.success_keywords, matched_profile.error_keywords
        )
        outcome.sync_status = status_result.status
        outcome.sync_status_evidence_text = status_result.matched_keyword
        outcome.confidence_sync = status_result.confidence

        # Meme logique qu'en mode application fixee (extraction_pipeline.py) :
        # certaines applications (ex. YEBCoach) ne confirment la synchronisation
        # que par une icone coloree, jamais par un mot-cle textuel. Reutilise les
        # frames de fin deja extraites — pas de nouveau decodage video.
        icon_zone = (matched_profile.screen_zones or {}).get("sync_status_icon")
        if icon_zone and outcome.sync_status == SyncStatus.UNCONFIRMED:
            for frame in outcome.extracted_frames:
                if frame.position != "end":
                    continue
                icon_result = detect_status_icon_color(frame.path, icon_zone)
                if icon_result.is_green:
                    outcome.sync_status = SyncStatus.SUCCESS
                    outcome.sync_status_evidence_text = (
                        f"Icone d'etat verte detectee dans la zone calibree "
                        f"({icon_result.green_ratio:.0%} de pixels verts)"
                    )
                    outcome.confidence_sync = min(0.5 + icon_result.green_ratio, 0.95)
                    outcome.review_reasons = [
                        reason for reason in outcome.review_reasons if "synchronisation" not in reason.lower()
                    ]
                    outcome.requires_manual_review = (
                        outcome.normalized_group_id is None or outcome.normalized_date is None
                    )
                    break

        return outcome, matched_profile.application

    outcome.requires_manual_review = True
    outcome.review_reasons.append("Application non identifiee automatiquement")
    return outcome, None


def _resolve_storage_path(evidence: EvidenceFile):
    from app.services.storage.storage_service import get_storage_service

    return get_storage_service().resolve(evidence.storage_path)


def _extract(evidence, resolved_path, profile: ApplicationProfile, known_ids, context_date_only):
    frames_dir = str(settings.frames_dir / evidence.id)
    if evidence.media_type == EvidenceType.VIDEO:
        return extract_from_video(
            resolved_path,
            frames_dir,
            evidence.id,
            profile.success_keywords or DEFAULT_SUCCESS_KEYWORDS,
            profile.error_keywords or DEFAULT_ERROR_KEYWORDS,
            known_ids=known_ids,
            context_date=context_date_only,
            start_offsets=profile.video_start_offsets_seconds,
            end_offsets=profile.video_end_offsets_seconds,
            status_icon_zone=(profile.screen_zones or {}).get("sync_status_icon"),
        )
    return extract_from_image(
        resolved_path,
        profile.success_keywords or DEFAULT_SUCCESS_KEYWORDS,
        profile.error_keywords or DEFAULT_ERROR_KEYWORDS,
        known_ids=known_ids,
        context_date=context_date_only,
    )


def _extract_generic(evidence, resolved_path, success_keywords, error_keywords, context_date_only):
    frames_dir = str(settings.frames_dir / evidence.id)
    if evidence.media_type == EvidenceType.VIDEO:
        return extract_from_video(
            resolved_path, frames_dir, evidence.id, success_keywords, error_keywords,
            known_ids=None, context_date=context_date_only,
        )
    return extract_from_image(
        resolved_path, success_keywords, error_keywords, known_ids=None, context_date=context_date_only
    )


def _persist_outcome(
    db: Session, evidence: EvidenceFile, outcome: ExtractionOutcome, application: Application | None
) -> None:
    if application is not None and evidence.application_id is None:
        evidence.application_id = application.id

    for frame in outcome.extracted_frames:
        from app.services.storage.storage_service import get_storage_service

        storage = get_storage_service()
        relative_path = storage.save(frame.path, subdirectory=f"frames/{evidence.id}")
        db.add(
            EvidenceFrame(
                evidence_id=evidence.id,
                position=frame.position,
                offset_seconds=frame.offset_seconds,
                storage_path=relative_path,
            )
        )

    for frame_debug in outcome.frame_debug:
        db.add(
            OcrResult(
                evidence_id=evidence.id,
                engine="easyocr+tesseract",
                raw_text=frame_debug.raw_text,
                normalized_text=frame_debug.raw_text.lower(),
                confidence=frame_debug.confidence,
            )
        )

    extraction = evidence.extraction or EvidenceExtraction(evidence_id=evidence.id)
    extraction.raw_group_id = outcome.raw_group_id
    extraction.normalized_group_id = outcome.normalized_group_id
    extraction.id_correction_method = outcome.id_correction_method
    extraction.raw_date = outcome.raw_date
    extraction.normalized_date = outcome.normalized_date
    extraction.date_is_ambiguous = outcome.date_is_ambiguous
    extraction.sync_status = outcome.sync_status
    extraction.sync_status_evidence_text = outcome.sync_status_evidence_text
    extraction.application_detected = application.code if application else None
    extraction.confidence_group_id = outcome.confidence_group_id
    extraction.confidence_date = outcome.confidence_date
    extraction.confidence_sync = outcome.confidence_sync
    extraction.global_confidence = outcome.global_confidence
    extraction.raw_ocr_text = outcome.raw_ocr_text
    extraction.requires_manual_review = outcome.requires_manual_review
    if evidence.extraction is None:
        db.add(extraction)
        evidence.extraction = extraction

    if outcome.requires_manual_review:
        reason = "; ".join(outcome.review_reasons) or "Confiance insuffisante"
        existing_review = (
            db.query(ManualReview)
            .filter(ManualReview.evidence_id == evidence.id, ManualReview.decision == "PENDING")
            .first()
        )
        if existing_review is None:
            db.add(ManualReview(evidence_id=evidence.id, reason=reason))
