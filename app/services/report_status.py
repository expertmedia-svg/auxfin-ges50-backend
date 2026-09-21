"""Exclusive dashboard categories, also used by the evidence list."""
from sqlalchemy import and_, func, not_, or_

from app.models.evidence import EvidenceExtraction, EvidenceFile


def report_filters():
    duplicate = or_(EvidenceFile.is_duplicate_of_id.isnot(None), EvidenceFile.processing_status == "DUPLICATE")
    pending = and_(not_(duplicate), EvidenceFile.processing_status.in_(["PENDING", "QUEUED", "PROCESSING"]))
    valid = and_(not_(duplicate), EvidenceFile.processing_status == "COMPLETED",
                 EvidenceFile.application_id.isnot(None), EvidenceFile.extraction.has(and_(
                     EvidenceExtraction.sync_status == "SUCCESS",
                     EvidenceExtraction.requires_manual_review.is_(False),
                     EvidenceExtraction.date_is_ambiguous.is_(False),
                     func.length(func.coalesce(func.nullif(EvidenceExtraction.manually_corrected_group_id, ""),
                                               EvidenceExtraction.normalized_group_id, "")) > 0,
                     func.length(func.coalesce(func.nullif(EvidenceExtraction.manually_corrected_date, ""),
                                               EvidenceExtraction.normalized_date, "")) > 0)))
    return {"VALID": valid, "PENDING": pending, "DUPLICATE": duplicate,
            "NOT_VALIDATED": and_(not_(duplicate), not_(pending), not_(valid))}
