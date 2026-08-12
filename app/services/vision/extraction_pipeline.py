"""Orchestrateur du pipeline d'extraction : combine OCR, normalisation d'ID,
detection de date et detection de statut de synchronisation, pour une preuve
image ou video. Utilise par les taches Celery ET par les scripts d'inspection
manuelle (pas de duplication de logique).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.enums import SyncStatus
from app.services.video.frame_extractor import ExtractedFrame, VideoMetadata, extract_start_end_frames
from app.services.vision.date_parser import parse_date
from app.services.vision.id_normalizer import find_id_candidates, normalize_group_id
from app.services.vision.ocr_engine import best_result, combined_text, run_ocr_on_image_path
from app.services.vision.status_icon import IconColorResult, detect_status_icon_color
from app.services.vision.sync_status import detect_sync_status


@dataclass
class FrameOcrDebug:
    position: str
    offset_seconds: float
    path: str
    raw_text: str
    confidence: float


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
) -> ExtractionOutcome:
    ocr_results = run_ocr_on_image_path(image_path)
    text = combined_text(ocr_results)
    best = best_result(ocr_results)
    base_confidence = best.confidence if best else 0.0

    return _build_outcome(
        combined_ocr_text=text,
        start_text=text,
        end_text=text,
        base_ocr_confidence=base_confidence,
        success_keywords=success_keywords,
        error_keywords=error_keywords,
        known_ids=known_ids,
        context_date=context_date,
    )


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
    id_found = False

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
            )
        )
        _, candidate_norm, _, _, conf, _ = _resolve_id(text, known_ids)
        if candidate_norm:
            id_found = True
            best_id_confidence = max(best_id_confidence, conf)
            if conf >= 0.9:
                break

    end_text_parts: list[str] = []
    # Signal complementaire aux mots-cles textuels : certaines applications
    # (ex. YEBCoach, bug reel trouve en Phase C) ne confirment la
    # synchronisation que par une icone qui devient verte, sans jamais
    # afficher de texte de confirmation exploitable par l'OCR.
    icon_confirmation: IconColorResult | None = None
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
            )
        )
        status_result = detect_sync_status(text, success_keywords, error_keywords)
        if status_icon_zone and icon_confirmation is None:
            icon_result = detect_status_icon_color(frame.path, status_icon_zone)
            if icon_result.is_green:
                icon_confirmation = icon_result
        if status_result.status != SyncStatus.UNCONFIRMED or icon_confirmation is not None:
            break

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

    # L'icone verte ne fait que CONFIRMER un succes quand aucun mot-cle
    # textuel n'a rien trouve — elle ne remplace jamais un statut deja
    # determine par texte (echec ou succes textuel restent prioritaires),
    # et n'est jamais utilisee pour deduire un echec (trop peu fiable sur
    # l'echantillon reel observe : un simple bouton rouge d'action, sans
    # rapport avec un echec, peut aussi se trouver dans la zone calibree).
    if icon_confirmation is not None and outcome.sync_status == SyncStatus.UNCONFIRMED:
        outcome.sync_status = SyncStatus.SUCCESS
        outcome.sync_status_evidence_text = (
            f"Icone d'etat verte detectee dans la zone calibree "
            f"({icon_confirmation.green_ratio:.0%} de pixels verts)"
        )
        outcome.confidence_sync = min(0.5 + icon_confirmation.green_ratio, 0.95)
        outcome.review_reasons = [
            reason for reason in outcome.review_reasons
            if "synchronisation" not in reason.lower()
        ]
        outcome.requires_manual_review = (
            outcome.normalized_group_id is None or outcome.normalized_date is None
        )
        # Recalcule la confiance globale (meme formule que _build_outcome)
        # avec le confidence_sync mis a jour, pour rester cohérente.
        updated_confidences = [
            outcome.confidence_group_id, outcome.confidence_date, outcome.confidence_sync, avg_conf,
        ]
        outcome.global_confidence = round(
            sum(c for c in updated_confidences if c) / max(len([c for c in updated_confidences if c]), 1), 3
        )
    if not id_found:
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
    requires_review = normalized_id is None or date_result.normalized_date is None

    if status_result.status == SyncStatus.UNCONFIRMED:
        reasons.append("Statut de synchronisation non confirme par mot-cle de succes ou d'echec")
        requires_review = True

    confidences = [id_confidence, date_result.confidence, status_result.confidence, base_ocr_confidence]
    global_confidence = sum(c for c in confidences if c) / max(len([c for c in confidences if c]), 1)

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
