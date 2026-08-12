from datetime import datetime

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    report_type: str = Field(pattern="^(daily|weekly|monthly|custom)$")
    format: str = Field(pattern="^(xlsx|csv|pdf)$")
    period_start: str | None = None
    period_end: str | None = None
    application_id: str | None = None
    reconciliation_run_id: str | None = None


class ReportOut(BaseModel):
    id: str
    report_type: str
    format: str
    status: str
    period_start: str | None
    period_end: str | None
    application_id: str | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
