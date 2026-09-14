"""Orchestrateur du pipeline d'extraction : combine OCR, normalisation d'ID,
detection de date et detection de statut de synchronisation, pour une preuve
image ou video. Utilise par les taches Celery ET par les scripts d'inspection
manuelle (pas de duplication de logique).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.config import get_settings
from app.models.enums import SyncStatus
from app.services.video.frame_extractor import ExtractedFrame, VideoMetadata, extract_start_end_frames
from app.services.vision.date_parser import parse_date
from app.services.vision.id_normalizer import find_id_candidates, normalize_group_id
from app.services.vision.ocr_engine import best_result, combined_text, run_ocr_on_image_path
from app.services.vision.status_icon import detect_status_icon_color
from app.services.vision.sync_status import detect_sync_status


@dataclass
class FrameOcrDebug:
    position: str
    offset_seconds: float
    path: str
    raw_text: str
    confidence: float
    engine: str = "easyocr+tesseract"


@dataclass
class ExtractionOutcome:
    raw_group_id: str | None
    normalized_group_id: str | None
    id_correction_method: str | None
    id_fuzzy_candidates: list[tuple[str, float]]

    raw_date: str | None
    normalized_date: str | None
    date_is_ambiguous: bool

    sync_status: SyncStatus
    sync_status_evidence_text: str | None

    confidence_group_id: float
    confidence_date: float
    confidence_sync: float
    global_confidence: float

    raw_ocr_text: str
    requires_manual_review: bool
    review_reasons: list[str] = field(default_factory=list)

    extracted_frames: list[ExtractedFrame] = field(default_factory=list)
    frame_debug: list[FrameOcrDebug] = field(default_factory=list)
    video_metadata: VideoMetadata | None = None


def _best_id_from_text(text: str, known_ids: list[str] | None) -> tuple[str | None, object | None]:
    for candidate in find_id_candidates(text):
        result = normalize_group_id(candidate, known_ids=known_ids)
        if result.is_valid_format or result.fuzzy_match:
            return candidate, result
    return None, None


def _resolve_id(text: str, known_ids: list[str] | None):
    raw_candidate, norm_result = _best_id_from_text(text, known_ids)
    if norm_result is None:
        return None, None, None, [], 0.0, ["Aucun identifiant de groupe detecte dans le texte OCR"]

    reasons: list[str] = []
    final_id = norm_result.normalized
    method = "regex" if norm_result.is_valid_format and not norm_result.corrections else (
        "regex_corrige" if norm_result.is_valid_format else None
    )
    confidence = norm_result.confidence

    if norm_result.fuzzy_match and (not norm_result.is_valid_format or norm_result.fuzzy_match != final_id):
        if norm_result.requires_manual_review:
            reasons.append(
                f"Correspondance floue ambigue avec les IDs connus (meilleur: {norm_result.fuzzy_match}, "
                f"score {norm_result.fuzzy_score})"
            )
        else:
            final_id = norm_result.fuzzy_match
            method = "correction_floue"
            confidence = (norm_result.fuzzy_score or 0) / 100

    if norm_result.requires_manual_review and not reasons:
        reasons.append("Format d'identifiant non reconnu avec certitude")

    return raw_candidate, final_id, method, norm_result.fuzzy_candidates, confidence, reasons


def _resolve_date(text: str, context_date: date | None):
    result = parse_date(text, context_date=context_date)
    reasons = list(result.notes) if result.normalized_date is None else []
    if result.is_ambiguous and result.normalized_date is not None:
        reasons.append("Date deduite partiellement (annee absente sur la preuve)")
    return result, reasons


def extract_from_image(
    image_path: str,
    success_keywords: list[str],
    error_keywords: list[str],
    known_ids: list[str] | None = None,
    context_date: date | None = None,
    status_icon_zone: dict | None = None,
) -> ExtractionOutcome:
    ocr_results = run_ocr_on_image_path(image_path)
    text = combined_text(ocr_results)
    best = best_result(ocr_results)
    base_confidence = best.confidence if best else 0.0

    outcome = _build_outcome(
        combined_ocr_text=text,
        start_text=text,
        end_text=text,
        base_ocr_confidence=base_confidence,
        success_keywords=success_keywords,
        error_keywords=error_keywords,
        known_ids=known_ids,
        context_date=context_date,
    )
    outcome.frame_debug = [FrameOcrDebug("end", 0, image_path, text, base_confidence,
                                         "+".join(sorted({r.engine for r in ocr_results})))]
    if status_icon_zone:
        apply_icon_confirmation(outcome, image_path, status_icon_zone)
    return outcome


def apply_icon_confirmation(outcome: ExtractionOutcome, path: str, zone: dict) -> None:
    if outcome.sync_status != SyncStatus.UNCONFIRMED:
        return
    # Une opération explicitement en attente / en cours reste non confirmée.
    if outcome.sync_status_evidence_text:
        return
    result = detect_status_icon_color(path, zone)
    if result.is_green:
        outcome.sync_status = SyncStatus.SUCCESS
        outcome.sync_status_evidence_text = f"Icone verte dans la zone calibree ({result.green_ratio:.0%})"
        outcome.confidence_sync = min(0.5 + result.green_ratio, 0.95)
        outcome.review_reasons = [r for r in outcome.review_reasons if r != SYNC_REVIEW_REASON]
        outcome.requires_manual_review = bool(outcome.review_reasons)
        recompute_confidence(outcome)


SYNC_REVIEW_REASON = "Statut de synchronisation non confirme par mot-cle de succes ou d'echec"


def recompute_confidence(outcome: ExtractionOutcome) -> None:
    ocr_confidence = max((f.confidence for f in outcome.frame_debug), default=0.0)
    outcome.global_confidence = round((outcome.confidence_group_id + outcome.confidence_date
                                       + outcome.confidence_sync + ocr_confidence) / 4, 3)


def refresh_sync_review(outcome: ExtractionOutcome) -> None:
    outcome.review_reasons = [r for r in outcome.review_reasons if r != SYNC_REVIEW_REASON]
    if outcome.sync_status != SyncStatus.SUCCESS:
        outcome.review_reasons.append(SYNC_REVIEW_REASON)
    outcome.requires_manual_review = bool(outcome.review_reasons)
    recompute_confidence(outcome)


def evaluate_sync_frames(outcome: ExtractionOutcome, success_keywords: list[str],
                         error_keywords: list[str], icon_zone: dict | None = None) -> None:
    """Dernier état explicite, dans l'ordre temporel, sans utiliser le début de vidéo."""
    latest = (SyncStatus.UNCONFIRMED, None, 0.0)
    for frame in sorted((f for f in outcome.frame_debug if f.position == "end"),
                        key=lambda f: f.offset_seconds, reverse=True):
        result = detect_sync_status(frame.raw_text, success_keywords, error_keywords)
        if result.matched_keyword:
            latest = (result.status, result.matched_keyword, result.confidence)
        elif icon_zone:
            icon = detect_status_icon_color(frame.path, icon_zone)
            if icon.is_green:
                latest = (SyncStatus.SUCCESS, f"Icone verte dans la zone calibree ({icon.green_ratio:.0%})",
                          min(0.5 + icon.green_ratio, 0.95))
    outcome.sync_status, outcome.sync_status_evidence_text, outcome.confidence_sync = latest
    refresh_sync_review(outcome)


def extract_from_video(
    video_path: str,
    frames_output_dir: str,
    evidence_id: str,
    success_keywords: list[str],
    error_keywords: list[str],
    known_ids: list[str] | None = None,
    context_date: date | None = None,
    start_offsets: list[float] | None = None,
    end_offsets: list[float] | None = None,
    status_icon_zone: dict | None = None,
) -> ExtractionOutcome:
    metadata, frames = extract_start_end_frames(
        video_path, frames_output_dir, evidence_id, start_offsets, end_offsets
    )

    start_frames = [f for f in frames if f.position == "start"]
    end_frames = [f for f in frames if f.position == "end"]

    start_text_parts: list[str] = []
    frame_debug: list[FrameOcrDebug] = []
    best_id_confidence = 0.0

    # On s'arrete des qu'un ID valide est trouve avec une confiance suffisante,
    # au lieu d'analyser systematiquement toutes les frames de debut.
    for frame in start_frames:
        ocr_results = run_ocr_on_image_path(frame.path)
        text = combined_text(ocr_results)
        best = best_result(ocr_results)
        start_text_parts.append(text)
        frame_debug.append(
            FrameOcrDebug(
                position=frame.position,
                offset_seconds=frame.offset_seconds,
                path=frame.path,
                raw_text=text,
                confidence=best.confidence if best else 0.0,
                engine="+".join(sorted({r.engine for r in ocr_results})),
            )
        )
        _, candidate_norm, _, _, conf, _ = _resolve_id(text, known_ids)
        if candidate_norm:
            best_id_confidence = max(best_id_confidence, conf)
            if conf >= 0.9:
                break

    end_text_parts: list[str] = []
    # Signal complementaire aux mots-cles textuels : certaines applications
    # (ex. YEBCoach, bug reel trouve en Phase C) ne confirment la
    # synchronisation que par une icone qui devient verte, sans jamais
    # afficher de texte de confirmation exploitable par l'OCR.
    for frame in end_frames:
        ocr_results = run_ocr_on_image_path(frame.path)
        text = combined_text(ocr_results)
        best = best_result(ocr_results)
        end_text_parts.append(text)
        frame_debug.append(
            FrameOcrDebug(
                position=frame.position,
                offset_seconds=frame.offset_seconds,
                path=frame.path,
                raw_text=text,
                confidence=best.confidence if best else 0.0,
                engine="+".join(sorted({r.engine for r in ocr_results})),
            )
        )
        # Ne s'arrete tot que si l'ID est deja connu (trouve dans les frames de
        # debut) : sinon on continue de scanner les frames de fin restantes,
        # car certaines applications n'affichent l'ID que sur l'ecran final
        # (bug reel signale : ID jamais capte quand il n'apparait qu'en toute
        # fin de video, la confirmation de sync arrivant sur une frame plus
        # tot dans la boucle interrompait le scan avant d'y arriver).
        # Analyser toutes les frames de fin : une erreur ultérieure doit
        # primer sur une confirmation antérieure.

    start_text = "\n".join(start_text_parts)
    end_text = "\n".join(end_text_parts)
    combined = start_text + "\n" + end_text

    avg_conf = (
        sum(fd.confidence for fd in frame_debug) / len(frame_debug) if frame_debug else 0.0
    )

    outcome = _build_outcome(
        combined_ocr_text=combined,
        start_text=start_text,
        end_text=end_text,
        base_ocr_confidence=avg_conf,
        success_keywords=success_keywords,
        error_keywords=error_keywords,
        known_ids=known_ids,
        context_date=context_date,
    )
    outcome.extracted_frames = frames
    outcome.frame_debug = frame_debug
    outcome.video_metadata = metadata

    evaluate_sync_frames(outcome, success_keywords, error_keywords, status_icon_zone)
    if outcome.normalized_group_id is None:
        outcome.review_reasons.append(
            "Aucun identifiant fiable trouve dans les frames de debut analysees"
        )
        outcome.requires_manual_review = True
    return outcome


def _build_outcome(
    *,
    combined_ocr_text: str,
    start_text: str,
    end_text: str,
    base_ocr_confidence: float,
    success_keywords: list[str],
    error_keywords: list[str],
    known_ids: list[str] | None,
    context_date: date | None,
) -> ExtractionOutcome:
    raw_id, normalized_id, method, fuzzy_candidates, id_confidence, id_reasons = _resolve_id(
        start_text, known_ids
    )
    if normalized_id is None and end_text.strip():
        # Repli : certaines apps affichent l'ID en permanence dans un bandeau,
        # donc il peut aussi apparaitre dans les frames de fin si les frames
        # de debut etaient trop bruitees pour l'OCR.
        raw_id, normalized_id, method, fuzzy_candidates, id_confidence, id_reasons = _resolve_id(
            combined_ocr_text, known_ids
        )

    date_result, date_reasons = _resolve_date(start_text, context_date)
    if date_result.normalized_date is None and end_text.strip():
        date_result, date_reasons = _resolve_date(combined_ocr_text, context_date)
    status_result = detect_sync_status(end_text, success_keywords, error_keywords)

    reasons = list(id_reasons) + list(date_reasons)
    if base_ocr_confidence < get_settings().ocr_confidence_threshold:
        reasons.append("Image insuffisamment lisible : renvoyer une capture nette de l'ecran complet")

    if status_result.status != SyncStatus.SUCCESS:
        reasons.append(SYNC_REVIEW_REASON)
    requires_review = bool(reasons)

    confidences = [id_confidence, date_result.confidence, status_result.confidence, base_ocr_confidence]
    global_confidence = sum(confidences) / len(confidences)

    return ExtractionOutcome(
        raw_group_id=raw_id,
        normalized_group_id=normalized_id,
        id_correction_method=method,
        id_fuzzy_candidates=fuzzy_candidates,
        raw_date=date_result.raw_text,
        normalized_date=date_result.normalized_date,
        date_is_ambiguous=date_result.is_ambiguous,
        sync_status=status_result.status,
        sync_status_evidence_text=status_result.matched_keyword,
        confidence_group_id=id_confidence,
        confidence_date=date_result.confidence,
        confidence_sync=status_result.confidence,
        global_confidence=round(global_confidence, 3),
        raw_ocr_text=combined_ocr_text,
        requires_manual_review=requires_review,
        review_reasons=reasons,
    )
