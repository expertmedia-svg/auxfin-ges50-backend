from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import ADMIN_ROLES, READ_ROLES, WRITE_ROLES
from app.models.enums import ProcessingStatus, WhatsAppDownloadStatus
from app.models.evidence import EvidenceFile
from app.models.identity import User
from app.models.whatsapp import WhatsAppGatewayStatus, WhatsAppGroup, WhatsAppMessage
from app.schemas.whatsapp import (
    WhatsAppGatewayStatusOut,
    WhatsAppGroupOut,
    WhatsAppGroupUpdate,
    WhatsAppMessageOut,
    WhatsAppMessageWebhookIn,
    WhatsAppQueueSummary,
    WhatsAppStatusWebhookIn,
)
from app.services.whatsapp import gateway_client, ingestion
from app.services.whatsapp.gateway_client import GatewayUnavailableError

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
settings = get_settings()


def _verify_gateway_token(x_gateway_token: str | None = Header(default=None)) -> None:
    if not settings.whatsapp_gateway_shared_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WHATSAPP_GATEWAY_SHARED_SECRET non configure cote backend : webhooks desactives.",
        )
    if x_gateway_token != settings.whatsapp_gateway_shared_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton de passerelle invalide")


def _group_stats(db: Session, group: WhatsAppGroup) -> WhatsAppGroupOut:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    media_today = (
        db.query(func.count(WhatsAppMessage.id))
        .filter(
            WhatsAppMessage.group_id == group.id,
            WhatsAppMessage.download_status == WhatsAppDownloadStatus.DOWNLOADED.value,
            WhatsAppMessage.created_at >= today_start,
        )
        .scalar()
        or 0
    )
    error_count = (
        db.query(func.count(WhatsAppMessage.id))
        .filter(WhatsAppMessage.group_id == group.id, WhatsAppMessage.download_status == WhatsAppDownloadStatus.FAILED.value)
        .scalar()
        or 0
    )
    return WhatsAppGroupOut(
        id=group.id,
        whatsapp_group_external_id=group.whatsapp_group_external_id,
        name=group.name,
        is_monitored=group.is_monitored,
        application_id=group.application_id,
        supervisor_id=group.supervisor_id,
        zone_label=group.zone_label,
        last_activity_at=group.last_activity_at,
        media_received_today=media_today,
        error_count=error_count,
    )


@router.get("/status", response_model=WhatsAppGatewayStatusOut)
def get_status(db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))) -> WhatsAppGatewayStatus:
    row = db.query(WhatsAppGatewayStatus).order_by(WhatsAppGatewayStatus.created_at.desc()).first()
    if row is None:
        row = WhatsAppGatewayStatus()
    return row


@router.get("/qr")
def get_qr_code(_: User = Depends(require_roles(*ADMIN_ROLES))) -> dict:
    try:
        control_status = gateway_client.get_control_status()
    except GatewayUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Service whatsapp-gateway injoignable: {exc}"
        ) from exc
    return {
        "connection_state": control_status.get("connection_state"),
        "qr_data_url": control_status.get("qr_data_url"),
    }


@router.post("/connect")
def connect(
    db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))
) -> dict:
    try:
        result = gateway_client.start_session()
    except GatewayUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Service whatsapp-gateway injoignable: {exc}"
        ) from exc
    record_audit(db, user_id=user.id, action="whatsapp.connect")
    db.commit()
    return result


@router.post("/disconnect")
def disconnect(
    db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))
) -> dict:
    try:
        result = gateway_client.stop_session()
    except GatewayUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Service whatsapp-gateway injoignable: {exc}"
        ) from exc
    record_audit(db, user_id=user.id, action="whatsapp.disconnect")
    db.commit()
    return result


@router.get("/groups", response_model=list[WhatsAppGroupOut])
def list_groups(
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[WhatsAppGroupOut]:
    query = db.query(WhatsAppGroup)
    if search:
        query = query.filter(WhatsAppGroup.name.ilike(f"%{search}%"))
    groups = query.order_by(WhatsAppGroup.name).all()
    return [_group_stats(db, group) for group in groups]


@router.post("/groups/refresh", response_model=list[WhatsAppGroupOut])
def refresh_groups(
    db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN_ROLES))
) -> list[WhatsAppGroupOut]:
    try:
        live_groups = gateway_client.refresh_groups()
    except GatewayUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Service whatsapp-gateway injoignable: {exc}"
        ) from exc

    for live in live_groups:
        existing = (
            db.query(WhatsAppGroup)
            .filter(WhatsAppGroup.whatsapp_group_external_id == live["whatsapp_group_external_id"])
            .first()
        )
        if existing is None:
            db.add(
                WhatsAppGroup(
                    whatsapp_group_external_id=live["whatsapp_group_external_id"],
                    name=live["name"],
                    is_monitored=False,
                )
            )
        else:
            existing.name = live["name"]

    record_audit(db, user_id=user.id, action="whatsapp.groups_refresh", details={"count": len(live_groups)})
    db.commit()

    groups = db.query(WhatsAppGroup).order_by(WhatsAppGroup.name).all()
    return [_group_stats(db, group) for group in groups]


@router.patch("/groups/{group_id}", response_model=WhatsAppGroupOut)
def update_group(
    group_id: str,
    payload: WhatsAppGroupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> WhatsAppGroupOut:
    group = db.get(WhatsAppGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Groupe WhatsApp introuvable")

    if payload.is_monitored is not None and payload.is_monitored != group.is_monitored:
        group.is_monitored = payload.is_monitored
        record_audit(
            db, user_id=user.id, action="whatsapp.group_enable" if payload.is_monitored else "whatsapp.group_disable",
            entity_type="whatsapp_group", entity_id=group.id, details={"name": group.name},
        )
    if payload.application_id is not None:
        group.application_id = payload.application_id or None
    if payload.supervisor_id is not None:
        group.supervisor_id = payload.supervisor_id or None
    if payload.zone_label is not None:
        group.zone_label = payload.zone_label or None

    db.commit()
    return _group_stats(db, group)


@router.get("/messages", response_model=list[WhatsAppMessageOut])
def list_messages(
    group_id: str | None = None,
    download_status: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[WhatsAppMessage]:
    query = db.query(WhatsAppMessage)
    if group_id:
        query = query.filter(WhatsAppMessage.group_id == group_id)
    if download_status:
        query = query.filter(WhatsAppMessage.download_status == download_status)
    return query.order_by(WhatsAppMessage.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/messages/unassigned", response_model=list[WhatsAppMessageOut])
def list_unassigned_messages(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[WhatsAppMessage]:
    return (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.download_status == WhatsAppDownloadStatus.SKIPPED_UNAUTHORIZED_GROUP.value)
        .order_by(WhatsAppMessage.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/queue", response_model=WhatsAppQueueSummary)
def get_queue_summary(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> WhatsAppQueueSummary:
    def count(status_value: str) -> int:
        return db.query(func.count(WhatsAppMessage.id)).filter(WhatsAppMessage.download_status == status_value).scalar() or 0

    processing = (
        db.query(func.count(WhatsAppMessage.id))
        .join(EvidenceFile, WhatsAppMessage.evidence_id == EvidenceFile.id)
        .filter(EvidenceFile.processing_status.in_([ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING]))
        .scalar()
        or 0
    )
    return WhatsAppQueueSummary(
        pending=count(WhatsAppDownloadStatus.PENDING.value),
        downloading=count(WhatsAppDownloadStatus.DOWNLOADING.value),
        processing=processing,
        failed=count(WhatsAppDownloadStatus.FAILED.value),
        unassigned=count(WhatsAppDownloadStatus.SKIPPED_UNAUTHORIZED_GROUP.value),
    )


@router.get("/errors", response_model=list[WhatsAppMessageOut])
def list_errors(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[WhatsAppMessage]:
    return (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.download_status == WhatsAppDownloadStatus.FAILED.value)
        .order_by(WhatsAppMessage.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/messages/{message_id}/retry", response_model=WhatsAppMessageOut)
def retry_message(
    message_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))
) -> WhatsAppMessage:
    message = db.get(WhatsAppMessage, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message WhatsApp introuvable")
    try:
        return ingestion.retry_message(db, message)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/webhook/status", status_code=status.HTTP_204_NO_CONTENT)
def webhook_status(
    payload: WhatsAppStatusWebhookIn,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_gateway_token),
) -> None:
    ingestion.handle_status_webhook(db, payload)


@router.post("/webhook/message", status_code=status.HTTP_204_NO_CONTENT)
def webhook_message(
    payload: WhatsAppMessageWebhookIn,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_gateway_token),
) -> None:
    ingestion.handle_message_webhook(db, payload)
