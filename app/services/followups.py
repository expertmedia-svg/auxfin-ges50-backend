"""Un dossier reste ouvert tant qu'une preuve correspondante n'est pas exploitable."""
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.applications import Agent
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup
from app.models.whatsapp import WhatsAppMessage


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def recipient_for(db: Session, evidence: EvidenceFile) -> str | None:
    message = db.query(WhatsAppMessage).filter(WhatsAppMessage.evidence_id == evidence.id).first()
    if message and message.sender_external_id and re.fullmatch(r"\d+@(c\.us|lid)", message.sender_external_id):
        return message.sender_external_id
    agent = db.get(Agent, evidence.agent_id) if evidence.agent_id else None
    phone = evidence.sender_phone or (agent.whatsapp_phone if agent else None)
    if phone:
        digits = re.sub(r"[\s+().-]", "", phone)
        if re.fullmatch(r"\d{8,15}", digits):
            return digits + "@c.us"
    return None


def usable(evidence: EvidenceFile) -> bool:
    ex = evidence.extraction
    return bool(evidence.processing_status == "COMPLETED" and evidence.application_id and ex
                and ex.sync_status == "SUCCESS" and ex.effective_group_id and ex.effective_date
                and not ex.requires_manual_review and not ex.date_is_ambiguous
                and not evidence.is_duplicate_of_id)


def problem_reason(evidence: EvidenceFile) -> str | None:
    if evidence.is_duplicate_of_id or evidence.processing_status in ("PENDING", "QUEUED", "PROCESSING", "DUPLICATE"):
        return None
    if usable(evidence):
        return None
    ex = evidence.extraction
    reasons = []
    if evidence.processing_status == "FAILED":
        reasons.append("Analyse impossible : vérifier le fichier et renvoyer une capture nette")
    if not ex or not ex.raw_ocr_text.strip() or ex.global_confidence < 0.55:
        reasons.append("Image ou texte insuffisamment lisible")
    if not evidence.application_id:
        reasons.append("Application non identifiée")
    if not ex or not ex.effective_group_id:
        reasons.append("Identifiant du groupe absent ou illisible")
    if not ex or not ex.effective_date or ex.date_is_ambiguous:
        reasons.append("Date du rapport absente ou ambiguë")
    if not ex or ex.sync_status != "SUCCESS":
        reasons.append("Synchronisation échouée" if ex and ex.sync_status == "FAILED" else "Synchronisation non confirmée")
    return "; ".join(reasons) or "Preuve à vérifier avant confirmation"


def same_sender(db: Session, original: EvidenceFile, replacement: EvidenceFile) -> bool:
    if original.agent_id and replacement.agent_id:
        return original.agent_id == replacement.agent_id
    recipient = recipient_for(db, original)
    return bool(recipient and recipient == recipient_for(db, replacement))


def matches(db: Session, original: EvidenceFile, replacement: EvidenceFile) -> bool:
    a, b = original.extraction, replacement.extraction
    # Aucun rapprochement automatique par le seul nom / téléphone : un agent
    # peut envoyer plusieurs applications, groupes et périodes le même jour.
    return bool(usable(replacement) and same_sender(db, original, replacement)
                and original.application_id == replacement.application_id
                and utc_naive(replacement.received_at) >= utc_naive(original.received_at)
                and a and b and a.effective_group_id and a.effective_date
                and a.effective_group_id == b.effective_group_id and a.effective_date == b.effective_date)


def update_followups(db: Session, evidence: EvidenceFile) -> None:
    reason = problem_reason(evidence)
    task = db.query(EvidenceFollowup).filter_by(evidence_id=evidence.id).first()
    if reason:
        if task is None:
            db.add(EvidenceFollowup(evidence_id=evidence.id, reason=reason))
        elif task.status != "RESOLVED":
            task.reason = reason
    if usable(evidence):
        for pending in db.query(EvidenceFollowup).filter(EvidenceFollowup.status != "RESOLVED").all():
            original = db.get(EvidenceFile, pending.evidence_id)
            if original and (original.id == evidence.id or matches(db, original, evidence)):
                pending.status = "RESOLVED"
                pending.replacement_evidence_id = evidence.id
                pending.resolved_at = datetime.utcnow()
