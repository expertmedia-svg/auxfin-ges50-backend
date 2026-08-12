from datetime import datetime

from pydantic import BaseModel


class ReconciliationRunCreate(BaseModel):
    application_id: str | None = None
    dashboard_import_id: str | None = None
    date_tolerance_days: int = 0
    period_start: str | None = None
    period_end: str | None = None


class ReconciliationRunOut(BaseModel):
    id: str
    application_id: str | None
    dashboard_import_id: str | None
    date_tolerance_days: int
    status: str
    summary: dict
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationResultOut(BaseModel):
    id: str
    run_id: str
    application_id: str | None
    status: str
    whatsapp_group_id: str | None
    dashboard_group_id: str | None
    whatsapp_date: str | None
    dashboard_date: str | None
    evidence_id: str | None
    agent_id: str | None
    locality: str | None
    confidence: float
    comment: str | None

    model_config = {"from_attributes": True}
