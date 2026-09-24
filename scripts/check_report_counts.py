"""Read-only dashboard diagnostic. No media reprocessing or messages."""
from app.core.database import SessionLocal
from app.models.evidence import EvidenceFile
from app.services.report_status import report_filters

with SessionLocal() as db:
    for label, condition in report_filters().items():
        print(label, db.query(EvidenceFile).filter(condition).count())
