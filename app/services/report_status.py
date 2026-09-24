"""Exclusive dashboard categories, also used by the evidence list."""
from sqlalchemy import and_, not_, or_

from app.models.evidence import EvidenceExtraction, EvidenceFile


def report_filters():
    duplicate = or_(EvidenceFile.is_duplicate_of_id.isnot(None), EvidenceFile.processing_status == "DUPLICATE")
    pending = and_(not_(duplicate), EvidenceFile.processing_status.in_(["PENDING", "QUEUED", "PROCESSING"]))
    valid = and_(not_(duplicate), EvidenceFile.processing_status.in_(["COMPLETED", "REQUIRES_REVIEW"]),
                 EvidenceFile.extraction.has(EvidenceExtraction.sync_status == "SUCCESS"))
    sync_visible = and_(not_(duplicate), not_(pending), EvidenceFile.extraction.has(
        EvidenceExtraction.sync_status == "SUCCESS"))
    return {"SYNC_VISIBLE": sync_visible, "SYNC_REVIEW": and_(sync_visible, not_(valid)), "VALID": valid, "PENDING": pending, "DUPLICATE": duplicate,
            "NOT_VALIDATED": and_(not_(duplicate), not_(pending), not_(valid))}
