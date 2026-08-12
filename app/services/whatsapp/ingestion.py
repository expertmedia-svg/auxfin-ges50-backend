"""Traitement des evenements pousses par le service Node whatsapp-gateway.

Le gateway ne prend aucune decision metier : il capture les messages/medias
et les transmet tels quels. Toute la logique (whitelist de groupe,
deduplication, association a une application, declenchement du pipeline
OCR) vit ici, exactement comme pour l'upload manuel
(voir app/api/routers/evidence.py::upload_evidence)."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.models.applications import Agent
from app.models.enums import EvidenceSource, ProcessingStatus, WhatsAppDownloadStatus
from app.models.whatsapp import WhatsAppGatewayStatus, WhatsAppGroup, WhatsAppMessage
from app.schemas.whatsapp import WhatsAppMessageWebhookIn, WhatsAppStatusWebhookIn
from app.services.evidence_service import register_evidence
from app.services.ingestion.base import IngestedFile

MAX_RETRY_ATTEMPTS = 5


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _resolve_agent(db: Session, sender_phone: str | None) -> Agent | None:
    if not sender_phone:
        return None
    normalized = _normalize_phone(sender_phone)
    if not normalized:
        return None
    for agent in db.query(Agent).filter(Agent.whatsapp_phone.isnot(None)):
        if _normalize_phone(agent.whatsapp_phone) == normalized:
            return agent
    return None


def _enqueue(evidence_id: str) -> None:
    # Import tardif : evite un import circulaire au chargement du module
    # (app.api.routers.evidence importe deja app.services.evidence_service),
    # meme pattern que app/api/routers/evidence.py::_enqueue_processing.
    from app.api.routers.evidence import _enqueue_processing

    _enqueue_processing(evidence_id)


def handle_status_webhook(db: Session, payload: WhatsAppStatusWebhookIn) -> WhatsAppGatewayStatus:
    row = db.query(WhatsAppGatewayStatus).order_by(WhatsAppGatewayStatus.created_at.desc()).first()
    if row is None:
        row = WhatsAppGatewayStatus()
        db.add(row)

    previous_state = row.connection_state
    row.connection_state = payload.connection_state
    row.phone_number = payload.phone_number
    row.display_name = payload.display_name
    row.last_error = payload.last_error
    row.connected_at = payload.connected_at
    from datetime import UTC, datetime

    row.last_heartbeat_at = datetime.now(UTC)

    if previous_state != payload.connection_state:
        record_audit(
            db, user_id=None, action=f"whatsapp.state_{payload.connection_state.lower()}",
            entity_type="whatsapp_gateway", details={"previous": previous_state, "new": payload.connection_state},
        )
    db.commit()
    db.refresh(row)
    return row


def handle_message_webhook(db: Session, payload: WhatsAppMessageWebhookIn) -> WhatsAppMessage:
    existing = (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.whatsapp_message_id == payload.whatsapp_message_id)
        .first()
    )
    if existing is not None:
        # Idempotence : le meme message WhatsApp peut etre repousse (reconnexion,
        # nouvelle tentative cote gateway). On ne le retraite jamais deux fois.
        return existing

    group = (
        db.query(WhatsAppGroup)
        .filter(WhatsAppGroup.whatsapp_group_external_id == payload.group_external_id)
        .first()
    )
    if group is None:
        # Groupe jamais vu : cree en decouverte passive, jamais surveille par
        # defaut (section 5 : "un groupe peut etre active" - jamais automatique).
        group = WhatsAppGroup(
            whatsapp_group_external_id=payload.group_external_id,
            name=payload.group_name or payload.group_external_id,
            is_monitored=False,
        )
        db.add(group)
        db.flush()

    from datetime import UTC, datetime

    group.last_activity_at = datetime.now(UTC)

    message = WhatsAppMessage(
        whatsapp_message_id=payload.whatsapp_message_id,
        group_id=group.id,
        group_external_id=payload.group_external_id,
        sender_external_id=payload.sender_external_id,
        sender_name=payload.sender_name,
        sender_phone=payload.sender_phone,
        message_date=payload.message_date,
        message_type=payload.message_type,
        caption_text=payload.caption_text,
        media_external_id=payload.media_external_id,
        media_filename=payload.media_filename,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        sha256=payload.sha256,
        storage_path=payload.storage_path,
        download_status=payload.download_status,
        last_error=payload.last_error,
    )
    db.add(message)
    db.flush()

    if payload.download_status != WhatsAppDownloadStatus.DOWNLOADED.value:
        record_audit(
            db, user_id=None, action="whatsapp.message_failed", entity_type="whatsapp_message",
            entity_id=message.id, details={"error": payload.last_error, "group": group.name},
        )
        db.commit()
        db.refresh(message)
        return message

    if not group.is_monitored:
        message.download_status = WhatsAppDownloadStatus.SKIPPED_UNAUTHORIZED_GROUP.value
        record_audit(
            db, user_id=None, action="whatsapp.message_unassigned", entity_type="whatsapp_message",
            entity_id=message.id, details={"group": group.name, "group_external_id": group.whatsapp_group_external_id},
        )
        db.commit()
        db.refresh(message)
        return message

    if not payload.storage_path or not Path(payload.storage_path).exists():
        message.download_status = WhatsAppDownloadStatus.FAILED.value
        message.last_error = "Fichier media introuvable sur disque au moment du traitement backend"
        record_audit(
            db, user_id=None, action="whatsapp.message_failed", entity_type="whatsapp_message", entity_id=message.id,
            details={"error": message.last_error},
        )
        db.commit()
        db.refresh(message)
        return message

    agent = _resolve_agent(db, payload.sender_phone)
    ingested = IngestedFile(
        source_path=Path(payload.storage_path),
        original_filename=payload.media_filename or f"{payload.whatsapp_message_id}.bin",
        sender_name=payload.sender_name,
        sender_phone=payload.sender_phone,
        whatsapp_message_date=payload.message_date,
    )
    evidence = register_evidence(
        db, ingested, EvidenceSource.WHATSAPP_GATEWAY,
        application_id=group.application_id, agent_id=agent.id if agent else None,
    )
    db.flush()
    message.evidence_id = evidence.id

    # Le fichier a ete copie dans le stockage permanent par register_evidence ;
    # la copie brute dans l'inbox WhatsApp n'a plus besoin d'etre conservee.
    try:
        Path(payload.storage_path).unlink(missing_ok=True)
    except OSError:
        pass

    is_duplicate = evidence.processing_status == ProcessingStatus.DUPLICATE
    record_audit(
        db, user_id=None, action="whatsapp.message_downloaded", entity_type="whatsapp_message", entity_id=message.id,
        details={"evidence_id": evidence.id, "group": group.name, "duplicate": is_duplicate},
    )
    db.commit()
    db.refresh(message)

    if not is_duplicate:
        _enqueue(evidence.id)

    return message


def retry_message(db: Session, message: WhatsAppMessage) -> WhatsAppMessage:
    if message.retry_count >= MAX_RETRY_ATTEMPTS:
        raise ValueError(f"Nombre maximal de tentatives atteint ({MAX_RETRY_ATTEMPTS})")

    message.retry_count += 1
    record_audit(
        db, user_id=None, action="whatsapp.message_retry", entity_type="whatsapp_message", entity_id=message.id,
        details={"attempt": message.retry_count},
    )

    if message.evidence_id:
        message.download_status = WhatsAppDownloadStatus.DOWNLOADED.value
        db.commit()
        _enqueue(message.evidence_id)
    else:
        # Pas encore de preuve associee (echec de telechargement cote gateway) :
        # rien a rejouer cote backend, la relance reelle depend du gateway.
        db.commit()

    db.refresh(message)
    return message
