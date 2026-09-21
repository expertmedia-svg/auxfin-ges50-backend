from sqlalchemy import and_, func

from app.models.evidence import EvidenceExtraction, EvidenceFile


def readable_filter():
    return and_(EvidenceFile.processing_status.in_(["COMPLETED", "REQUIRES_REVIEW"]),
                EvidenceFile.extraction.has(and_(EvidenceExtraction.global_confidence >= .55,
                    func.length(func.trim(EvidenceExtraction.raw_ocr_text)) > 0)))
