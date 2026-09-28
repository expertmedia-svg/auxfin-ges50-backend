"""Offline media maintenance. Database results survive normal retention."""
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import delete, select, update
from app.core.database import Base
import app.models  # noqa: F401
from app.models.evidence import EvidenceFile, EvidenceFrame, ProcessingJob
from app.models.system import Report, SystemSetting
from app.models.whatsapp import WhatsAppMessage

RESET_TABLES = (
    'followup_messages', 'evidence_followups', 'daily_reminders', 'daily_reminder_runs',
    'manual_reviews', 'reports', 'reconciliation_results', 'reconciliation_runs',
    'ocr_results', 'evidence_frames', 'evidence_extractions', 'evidence_files',
)
MEDIA_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.mp4', '.mov', '.avi', '.mkv', '.3gp'}


def maintenance(db, root, *, reset=False, execute=False, now=None):
    now = now or datetime.utcnow()
    root = Path(root).resolve()
    files = db.query(EvidenceFile).all()
    active_ids = set(db.scalars(select(ProcessingJob.related_evidence_id).where(
        ProcessingJob.status.in_(['PENDING', 'QUEUED', 'RUNNING', 'PROCESSING']))))
    eligible = [e for e in files if reset or (
        e.received_at < now - timedelta(days=14)
        and e.processing_status not in ('PENDING', 'QUEUED', 'PROCESSING')
        and e.id not in active_ids)]
    ids = {e.id for e in eligible}
    paths = {e.storage_path for e in eligible}
    protected = {e.storage_path for e in files if e.id not in ids}
    for f in db.query(EvidenceFrame).all():
        (paths if f.evidence_id in ids else protected).add(f.storage_path)
    if reset:
        paths.update(r.storage_path for r in db.query(Report).all() if r.storage_path)
    safe = set()
    for stored in paths - protected:
        path = (root / stored).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Chemin de fichier hors stockage : suppression refusée')
        if path.parts[len(root.parts)] not in ('uploads', 'frames', 'reports'):
            raise ValueError('Dossier non autorisé : suppression refusée')
        if path.suffix.lower() not in MEDIA_SUFFIXES | ({'.pdf', '.xlsx', '.csv'} if reset else set()):
            raise ValueError('Type de fichier non autorisé : suppression refusée')
        if path.is_file():
            safe.add(path)
    summary = {'mode': 'reset' if reset else 'retention_14_days', 'execute': execute,
               'reports': len(ids), 'files': len(safe), 'bytes': sum(p.stat().st_size for p in safe),
               'protected_reports': len(files) - len(ids)}
    if not execute:
        return summary
    # Run with backend, worker, gateway and reminder cron stopped (see documentation).
    # Files are deleted first. On error, records remain and the command can be repeated.
    for path in safe:
        path.unlink(missing_ok=True)
    if reset:
        db.execute(update(WhatsAppMessage).values(evidence_id=None, storage_path=None, caption_text=None))
        db.execute(delete(ProcessingJob).where(ProcessingJob.related_evidence_id.isnot(None)))
        db.execute(delete(ProcessingJob).where(ProcessingJob.related_entity_type.in_(['reconciliation', 'report'])))
        db.execute(update(EvidenceFile).values(is_duplicate_of_id=None))
        for name in RESET_TABLES:
            db.execute(delete(Base.metadata.tables[name]))
        setting = db.query(SystemSetting).filter_by(key='reports_reset_at').first()
        if setting is None:
            setting = SystemSetting(key='reports_reset_at')
            db.add(setting)
        setting.value = {'utc': now.isoformat()}
    db.commit()
    return summary
