from datetime import datetime

from pydantic import BaseModel


class EvidenceFrameOut(BaseModel):
    id: str
    position: str
    offset_seconds: float
    storage_path: str
    is_selected_best: bool

    model_config = {"from_attributes": True}


class OcrResultOut(BaseModel):
    id: str
    engine: str
    raw_text: str
    confidence: float
    preprocessing_variant: str

    model_config = {"from_attributes": True}


class EvidenceExtractionOut(BaseModel):
    raw_group_id: str | None
    normalized_group_id: str | None
    id_correction_method: str | None
    raw_date: str | None
    normalized_date: str | None
    date_is_ambiguous: bool
    sync_status: str
    sync_status_evidence_text: str | None
    confidence_group_id: float
    confidence_date: float
    confidence_sync: float
    global_confidence: float
    requires_manual_review: bool
    manually_corrected_group_id: str | None
    manually_corrected_date: str | None

    model_config = {"from_attributes": True}


class EvidenceOut(BaseModel):
    id: str
    original_filename: str
    media_type: str
    mime_type: str
    file_size: int
    source: str
    processing_status: str
    application_id: str | None
    application_detected_id: str | None
    agent_id: str | None
    sender_name: str | None
    received_at: datetime
    is_duplicate_of_id: str | None
    extraction: EvidenceExtractionOut | None = None

    model_config = {"from_attributes": True}


class EvidenceUploadReport(BaseModel):
    total_files: int
    accepted: int
    rejected: int
    errors: list[str]
    evidence_ids: list[str]


class EvidenceCorrection(BaseModel):
    group_id: str | None = None
    sync_date: str | None = None
    application_id: str | None = None
    comment: str | None = None


class ManualReviewDecisionIn(BaseModel):
    comment: str | None = None
