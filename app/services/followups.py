"""Un dossier reste ouvert tant qu'une preuve correspondante n'est pas exploitable."""
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.applications import Agent
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup
from app.models.whatsapp import WhatsAppMessage


RECORDING_INSTRUCTIONS = (
    "Envoyez obligatoirement un enregistrement vidéo de l'écran (screen recording), "
    "réalisé directement avec la fonction Enregistrement d'écran du téléphone. "
    "Seules les vidéos d'enregistrement d'écran sont acceptées comme rapports. "
    "Il est interdit d'envoyer des selfies, des photos de vous-même, d'autres photos, "
    "des captures d'écran fixes ou tout autre contenu comme rapport. "
    "Ne filmez pas l'écran avec un deuxième téléphone : "
    "les reflets rendent les informations illisibles. "
    "Montrez l'application, l'identifiant du groupe, la date et la fin de la synchronisation "
    "avec son signe de réussite bien visible."
)


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
    return bool(ex and ex.sync_status == "SUCCESS"
                and evidence.processing_status in ("COMPLETED", "REQUIRES_REVIEW")
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
    identity = sender_identity(db, original)
    return bool(identity and identity == sender_identity(db, replacement))


def sender_identity(db: Session, evidence: EvidenceFile) -> str | None:
    if evidence.agent_id:
        return evidence.agent_id
    recipient = recipient_for(db, evidence)
    if recipient and recipient.endswith("@c.us"):
        candidates = [a.id for a in db.query(Agent).filter(Agent.whatsapp_phone.isnot(None))
                      if re.sub(r"[\s+().-]", "", a.whatsapp_phone) + "@c.us" == recipient]
        if len(candidates) == 1:
            return candidates[0]
    if recipient:
        linked = db.query(EvidenceFile.agent_id).join(WhatsAppMessage, WhatsAppMessage.evidence_id == EvidenceFile.id).filter(
            WhatsAppMessage.sender_external_id == recipient, EvidenceFile.agent_id.isnot(None)).distinct().all()
        if len(linked) == 1:
            return linked[0][0]
    return recipient


def matches(db: Session, original: EvidenceFile, replacement: EvidenceFile) -> bool:
    a, b = original.extraction, replacement.extraction
    # Aucun rapprochement automatique par le seul nom / téléphone : un agent
    # peut envoyer plusieurs applications, groupes et périodes le même jour.
    return bool(usable(replacement) and same_sender(db, original, replacement)
                and original.application_id is not None
                and original.application_id == replacement.application_id
                and utc_naive(replacement.received_at) >= utc_naive(original.received_at)
                and a and b and not b.date_is_ambiguous and a.effective_group_id and a.effective_date and not a.date_is_ambiguous
                and a.effective_group_id == b.effective_group_id and a.effective_date == b.effective_date)


def report_key(db: Session, evidence: EvidenceFile) -> tuple | None:
    """Une identité complète est nécessaire pour fusionner des demandes."""
    ex = evidence.extraction
    sender = sender_identity(db, evidence)
    if sender and evidence.application_id and ex and ex.effective_group_id and ex.effective_date and not ex.date_is_ambiguous:
        return sender, evidence.application_id, ex.effective_group_id, ex.effective_date
    return None


def update_followups(db: Session, evidence: EvidenceFile) -> None:
    # Une preuve de remplacement rejetée/corrigée ne doit pas laisser des
    # dossiers clôturés à tort. Une association manuelle reste possible pour
    # les originaux incomplets : on contrôle ici l'exploitabilité du retour.
    if not usable(evidence) and evidence.processing_status not in ("PENDING", "QUEUED", "PROCESSING"):
        for resolved in db.query(EvidenceFollowup).filter_by(
                replacement_evidence_id=evidence.id, status="RESOLVED"):
            resolved.status = "OPEN"
            resolved.replacement_evidence_id = None
            resolved.resolved_at = None
    reason = problem_reason(evidence)
    task = db.query(EvidenceFollowup).filter_by(evidence_id=evidence.id).first()
    if reason:
        if task is None:
            db.add(EvidenceFollowup(evidence_id=evidence.id, reason=reason))
        elif task.status != "RESOLVED":
            task.reason = reason
        # Le worker peut finir l'ancienne vidéo après sa correction. Rechercher
        # aussi les preuves déjà traitées, sans dépendre de l'ordre du worker.
        db.flush()
        task = db.query(EvidenceFollowup).filter_by(evidence_id=evidence.id).one()
        if task.status != "RESOLVED":
            candidates = db.query(EvidenceFile).filter(
                EvidenceFile.application_id == evidence.application_id,
                EvidenceFile.processing_status.in_(["COMPLETED", "REQUIRES_REVIEW"]),
                EvidenceFile.received_at >= evidence.received_at,
            ).order_by(EvidenceFile.received_at, EvidenceFile.id)
            for replacement in candidates:
                if matches(db, evidence, replacement):
                    task.status = "RESOLVED"
                    task.replacement_evidence_id = replacement.id
                    task.resolved_at = datetime.utcnow()
                    break
    if usable(evidence):
        for pending in db.query(EvidenceFollowup).filter(EvidenceFollowup.status != "RESOLVED").all():
            original = db.get(EvidenceFile, pending.evidence_id)
            if original and (original.id == evidence.id or matches(db, original, evidence)):
                pending.status = "RESOLVED"
                pending.replacement_evidence_id = evidence.id
                pending.resolved_at = datetime.utcnow()
