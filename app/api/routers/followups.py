from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup, FollowupMessage
from app.models.identity import User
from app.services.followups import (
    RECORDING_INSTRUCTIONS,
    recipient_for,
    report_key,
    same_sender,
    update_followups,
    usable,
    utc_naive,
)
from app.services.whatsapp.gateway_client import GatewayUnavailableError, send_reminder

router = APIRouter(prefix="/followups", tags=["followups"])


def suggested_message(task, evidence):
    ex = evidence.extraction
    context = f"{evidence.application.name if evidence.application else 'Application à préciser'} / "
    context += f"{ex.effective_group_id if ex and ex.effective_group_id else 'Groupe à préciser'} / "
    context += f"{ex.effective_date if ex and ex.effective_date else 'Date à préciser'}"
    return (f"Bonjour {evidence.sender_name or ''}, votre rapport ({context}) est à refaire. "
            f"Motif : {task.reason}. {RECORDING_INSTRUCTIONS} "
            "Renvoyez la correction dans le groupe WhatsApp d'origine. "
            "Ne répondez pas avec une vidéo ou une image dans ce chat privé. "
            "Envoyez vos autres rapports dans leurs groupes habituels. "
            f"Référence de suivi : {task.id}.")


@router.get("")
def list_followups(
    reference: str | None = Query(None, max_length=100),
    state: Literal["OPEN", "WAITING", "RESOLVED"] | None = None,
    view: Literal["OPEN", "WAITING", "RETURNED_INVALID", "RESOLVED"] | None = None,
    delay: int = Query(0, ge=0, le=365),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES)),
):
    query = db.query(EvidenceFollowup)
    if reference and reference.strip():
        query = query.filter(EvidenceFollowup.id == reference.strip())
    if state:
        query = query.filter_by(status=state)
    if view or delay:
        summary = dashboard(db, None)
        selected_ids = [task_id for row in summary["rows"]
                        if (not view or row["status"] == view)
                        and (not delay or (row["days_since_reminder"] is not None
                                           and row["days_since_reminder"] >= delay))
                        for task_id in row["related_followup_ids"]]
        query = query.filter(EvidenceFollowup.id.in_(selected_ids))
    total = query.count()
    items = []
    for task in query.order_by(EvidenceFollowup.created_at.desc(), EvidenceFollowup.id).offset(offset).limit(limit):
        evidence = db.get(EvidenceFile, task.evidence_id)
        messages = db.query(FollowupMessage).filter_by(followup_id=task.id).order_by(FollowupMessage.created_at.desc()).all()
        items.append({
            "id": task.id, "evidence_id": task.evidence_id, "reason": task.reason, "status": task.status,
            "sender_name": evidence.sender_name, "recipient": recipient_for(db, evidence),
            "application": evidence.application.name if evidence.application else None,
            "filename": evidence.original_filename, "created_at": task.created_at,
            "replacement_evidence_id": task.replacement_evidence_id,
            "suggested_message": suggested_message(task, evidence),
            "messages": [{"id": m.id, "status": m.status, "body": m.body, "error": m.error,
                          "created_at": m.created_at, "recipient": m.recipient} for m in messages],
        })
    return {"items": items, "total": total}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))):
    from collections import Counter, defaultdict

    from app.services.operations import OperationQuery, operational_data
    today = datetime.utcnow().date()
    data = operational_data(db, OperationQuery(dataset="followups", scope="all", start=today, end=today))
    monthly = defaultdict(list)
    for message in db.query(FollowupMessage).filter(FollowupMessage.status == "SENT"):
        if utc_naive(message.created_at).strftime("%Y-%m") == today.strftime("%Y-%m"):
            monthly[message.recipient].append(message.external_message_id or message.id)
    sent_by_task = defaultdict(list)
    for message in db.query(FollowupMessage).filter_by(status="SENT"):
        sent_by_task[message.followup_id].append(message)
    for row in data["rows"]:
        ids = row["related_followup_ids"]
        sent = [message for task_id in ids for message in sent_by_task[task_id]]
        last = max((utc_naive(m.created_at) for m in sent), default=None)
        row["sent_count"] = len(sent)
        row["last_sent_at"] = last.isoformat() if last else None
        row["days_since_reminder"] = (datetime.utcnow() - last).days if last else None
    return {"rows": data["rows"], "counts": dict(Counter(r["status"] for r in data["rows"])),
            "month": today.strftime("%Y-%m"),
            "frequent": [{"recipient": recipient, "sent_count": len(set(ids))}
                         for recipient, ids in monthly.items() if len(set(ids)) > 5]}


@router.get("/automatic-stats")
def automatic_stats(db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))):
    from collections import Counter

    from app.models.followup import DailyReminder, DailyReminderRun
    today = datetime.utcnow().date().isoformat()
    campaigns = db.query(DailyReminder).order_by(DailyReminder.day.desc(), DailyReminder.recipient).all()
    counts = Counter(c.status for c in campaigns if c.day == today)
    runs = db.query(DailyReminderRun).order_by(DailyReminderRun.created_at.desc()).limit(30).all()
    return {"day": today, "counts": dict(counts),
            "recipients": [{"day": c.day, "recipient": c.recipient, "status": c.status} for c in campaigns[:200]],
            "runs": [{"at": r.created_at, "result": r.result} for r in runs]}


@router.post("/refresh")
def refresh(db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))):
    # Inclut les rapports déjà traités avant l'installation du suivi.
    for evidence in db.query(EvidenceFile).filter(EvidenceFile.processing_status.notin_(["PENDING", "PROCESSING"])):
        update_followups(db, evidence)
        db.flush()
    # Deuxième passe : la nouvelle preuve peut précéder la création du dossier.
    for evidence in db.query(EvidenceFile).filter_by(processing_status="COMPLETED"):
        update_followups(db, evidence)
    record_audit(db, user_id=user.id, action="followup.refresh")
    db.commit()
    return {"ok": True}


class ReminderRequest(BaseModel):
    followup_ids: list[str] = Field(min_length=1, max_length=50)
    message: str | None = Field(default=None, min_length=1, max_length=3000)


@router.post("/send")
def send(payload: ReminderRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))):
    prepared = []
    reserved_keys = set()
    open_tasks = db.query(EvidenceFollowup).filter(EvidenceFollowup.status != "RESOLVED").all()
    keys = {t.id: report_key(db, db.get(EvidenceFile, t.evidence_id)) for t in open_tasks}
    for task_id in dict.fromkeys(payload.followup_ids):
        task = db.get(EvidenceFollowup, task_id)
        if not task or task.status == "RESOLVED":
            raise HTTPException(400, "Un dossier est introuvable ou déjà résolu. Actualisez la liste.")
        recipient = recipient_for(db, db.get(EvidenceFile, task.evidence_id))
        if not recipient:
            raise HTTPException(400, "Un destinataire est inconnu. Complétez le numéro WhatsApp de l'agent.")
        key = keys.get(task.id)
        if key and key in reserved_keys:
            continue  # Plusieurs fichiers du même rapport : un seul message.
        reserved_keys.add(key or task.id)
        related = sorted([t for t in open_tasks if t.id == task.id or (key and keys[t.id] == key)], key=lambda t: t.id)
        attempts = db.query(FollowupMessage).filter(FollowupMessage.followup_id.in_([t.id for t in related])).all()
        if any(m.status in ("SENDING", "UNKNOWN")
               or (datetime.utcnow() - utc_naive(m.created_at)).total_seconds() < 60 for m in attempts):
            raise HTTPException(409, "Envoi récent ou résultat incertain : vérifiez l'historique avant de relancer.")
        body = payload.message.strip() if payload.message else suggested_message(task, db.get(EvidenceFile, task.evidence_id))
        if payload.message:
            body += (f"\n{RECORDING_INSTRUCTIONS}\nRenvoyez chaque correction dans son groupe WhatsApp d'origine. "
                     "Ne répondez pas avec une vidéo ou une image dans ce chat privé. "
                     "Envoyez vos autres rapports dans leurs groupes habituels.")
        if not body:
            raise HTTPException(400, "Le message ne peut pas être vide.")
        # Comparaison atomique : deux opérateurs ne peuvent réserver le même
        # dossier avec la même version et envoyer deux relances simultanées.
        for sibling in related:
            claimed = db.execute(update(EvidenceFollowup).where(
                EvidenceFollowup.id == sibling.id, EvidenceFollowup.send_version == sibling.send_version,
                EvidenceFollowup.status != "RESOLVED",
            ).values(send_version=EvidenceFollowup.send_version + 1).execution_options(synchronize_session=False))
            if claimed.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "Ce rapport vient d'être modifié. Actualisez la liste.")
        attempt = FollowupMessage(followup_id=task.id, requested_by_id=user.id, recipient=recipient, body=body)
        db.add(attempt)
        prepared.append((task, attempt))
    db.commit()  # Toutes les réservations sont persistées avant le premier envoi.
    results = []
    for task, attempt in prepared:
        try:
            from app.services.reminder_media import reference_images
            media = reference_images([(task, db.get(EvidenceFile, task.evidence_id))])
            result = (send_reminder(attempt.recipient, attempt.body, media=media) if media else
                      send_reminder(attempt.recipient, attempt.body))
            attempt.external_message_id = result["message_id"]
            attempt.status = "SENT"
            # Une nouvelle preuve peut avoir résolu le dossier pendant l'envoi.
            db.execute(update(EvidenceFollowup).where(
                EvidenceFollowup.id == task.id, EvidenceFollowup.status != "RESOLVED",
            ).values(status="WAITING"))
        except GatewayUnavailableError:
            attempt.status = "UNKNOWN"
            attempt.error = "Envoi non confirmé par la passerelle. Vérifier WhatsApp avant toute nouvelle tentative."
        record_audit(db, user_id=user.id, action="followup.send", entity_id=task.id,
                     details={"attempt_id": attempt.id, "status": attempt.status})
        db.commit()
        results.append({"id": task.id, "status": attempt.status})
    return results


class ResolveRequest(BaseModel):
    replacement_evidence_id: str


@router.post("/{task_id}/resolve")
def resolve(task_id: str, payload: ResolveRequest, db: Session = Depends(get_db),
            user: User = Depends(require_roles(*WRITE_ROLES))):
    task = db.get(EvidenceFollowup, task_id)
    replacement = db.get(EvidenceFile, payload.replacement_evidence_id)
    if not task or not replacement:
        raise HTTPException(404, "Dossier ou preuve introuvable")
    original = db.get(EvidenceFile, task.evidence_id)
    if not usable(replacement) or not same_sender(db, original, replacement):
        raise HTTPException(400, "Choisissez une preuve exploitable du même agent.")
    a, b = original.extraction, replacement.extraction
    if (utc_naive(replacement.received_at) < utc_naive(original.received_at)
        or (original.application_id and original.application_id != replacement.application_id)
        or (a and a.effective_group_id and a.effective_group_id != b.effective_group_id)
        or (a and a.effective_date and a.effective_date != b.effective_date)):
        raise HTTPException(400, "La preuve ne correspond pas à l'application, au groupe ou à la période du dossier.")
    task.status = "RESOLVED"
    task.replacement_evidence_id = replacement.id
    task.resolved_at = datetime.utcnow()
    record_audit(db, user_id=user.id, action="followup.resolve", entity_id=task.id,
                 details={"replacement_evidence_id": replacement.id})
    db.commit()
    return {"ok": True}


@router.post("/{task_id}/acknowledge-unknown")
def acknowledge_unknown(task_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))):
    attempts = db.query(FollowupMessage).filter(FollowupMessage.followup_id == task_id,
                                             FollowupMessage.status.in_(["UNKNOWN", "SENDING"])).all()
    for attempt in attempts:
        if (datetime.utcnow() - utc_naive(attempt.created_at)).total_seconds() < 60:
            raise HTTPException(409, "Attendez la fin de l'envoi en cours.")
        attempt.status = "CHECKED"
    record_audit(db, user_id=user.id, action="followup.unknown_checked", entity_id=task_id)
    db.commit()
    return {"ok": True}
