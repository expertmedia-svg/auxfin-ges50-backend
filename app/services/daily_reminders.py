"""One private message per recipient/day; uncertain sends are never retried."""
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.permissions import WRITE_ROLES
from app.models.evidence import EvidenceFile
from app.models.followup import DailyReminder, EvidenceFollowup, FollowupMessage
from app.services.followups import RECORDING_INSTRUCTIONS, recipient_for, update_followups, utc_naive
from app.services.whatsapp.gateway_client import GatewayUnavailableError, send_reminder


def _run_daily(db, user, now=None, execute=False):
    now = now or datetime.now(UTC)
    now = utc_naive(now)  # Burkina Faso = UTC, sans changement saisonnier.
    if not user.is_active or not set(user.role_codes) & WRITE_ROLES:
        raise ValueError("Un opérateur actif autorisé est nécessaire.")
    if now.hour < 22:
        return {"status": "before_22h", "sent": 0}
    day = now.date().isoformat()
    if execute:
        for evidence in db.query(EvidenceFile).filter(EvidenceFile.processing_status.notin_(
                ["PENDING", "QUEUED", "PROCESSING", "DUPLICATE"])):
            update_followups(db, evidence)
            db.flush()
        db.commit()
    grouped = defaultdict(list)
    for task in db.query(EvidenceFollowup).filter(EvidenceFollowup.status != "RESOLVED"):
        ev = db.get(EvidenceFile, task.evidence_id)
        if utc_naive(ev.received_at).date().isoformat() != day:
            continue
        recipient = recipient_for(db, ev)
        if recipient:
            grouped[recipient].append((task, ev))
    result = {"sent": 0, "skipped": 0, "unknown": 0, "prepared": 0}
    for recipient, entries in grouped.items():
        existing = db.query(FollowupMessage).filter_by(recipient=recipient).all()
        if (db.get(DailyReminder, (day, recipient)) or any(
            m.status in ("SENDING", "UNKNOWN") or
            (m.status in ("SENT", "MANUALLY_CONFIRMED") and utc_naive(m.created_at).date().isoformat() == day) for m in existing)):
            result["skipped"] += 1
            continue
        lines = [f"Bonjour, voici vos rapports reçus le {day} à corriger :"]
        for index, (task, ev) in enumerate(entries, 1):
            ex = ev.extraction
            lines.append(f"{index}. {ev.application.name if ev.application else 'Application inconnue'} / "
                         f"{ex.effective_group_id if ex else 'Groupe illisible'} : {task.reason}. Réf. {task.id}")
        lines.append("Merci de renvoyer les preuves lisibles et synchronisées dans leur groupe WhatsApp d’origine.")
        lines.append(RECORDING_INSTRUCTIONS)
        lines.append("Ne répondez pas avec une vidéo ou une image dans ce chat privé. "
                     "Envoyez vos autres rapports dans leurs groupes habituels.")
        body = "\n".join(lines)
        if len(body) > 4000:
            result["skipped"] += 1  # Ne pas omettre silencieusement des dossiers.
            continue
        result["prepared"] += 1
        if not execute:
            continue
        attempts = []
        try:
            db.add(DailyReminder(day=day, recipient=recipient, status="SENDING"))
            db.flush()  # Unicité persistante, même en cas de deux processus simultanés.
            for task, _ in sorted(entries, key=lambda pair: pair[0].id):
                claimed = db.execute(update(EvidenceFollowup).where(
                    EvidenceFollowup.id == task.id, EvidenceFollowup.send_version == task.send_version,
                    EvidenceFollowup.status != "RESOLVED",
                ).values(send_version=EvidenceFollowup.send_version + 1).execution_options(synchronize_session=False))
                if claimed.rowcount != 1:
                    raise ValueError("Dossier modifié pendant la préparation")
                attempt = FollowupMessage(followup_id=task.id, requested_by_id=user.id,
                                          recipient=recipient, body=body, status="SENDING")
                db.add(attempt)
                attempts.append(attempt)
            db.commit()
        except (IntegrityError, ValueError):
            db.rollback()
            result["skipped"] += 1
            continue
        try:
            from app.services.reminder_media import reference_images
            media = reference_images(entries)
            response = send_reminder(recipient, body, media=media) if media else send_reminder(recipient, body)
            message_id = response["message_id"]
            status = "SENT"
            for attempt in attempts:
                attempt.external_message_id = message_id
                db.execute(update(EvidenceFollowup).where(EvidenceFollowup.id == attempt.followup_id,
                    EvidenceFollowup.status != "RESOLVED").values(status="WAITING"))
            result["sent"] += 1
        except GatewayUnavailableError:
            status = "UNKNOWN"
            result["unknown"] += 1
        for attempt in attempts:
            attempt.status = status
        db.get(DailyReminder, (day, recipient)).status = status
        db.commit()
    return result


def run_daily(db, user, now=None, execute=False):
    from app.models.followup import DailyReminderRun
    try:
        result = _run_daily(db, user, now, execute)
    except Exception:
        db.rollback()
        if execute:
            db.add(DailyReminderRun(result={"status": "ERROR"}))
            db.commit()
        raise
    if execute:
        db.add(DailyReminderRun(result=result))
        db.commit()
    return result
