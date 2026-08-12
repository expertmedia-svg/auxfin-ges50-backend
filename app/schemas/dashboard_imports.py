from datetime import datetime

from pydantic import BaseModel


class DashboardImportPreview(BaseModel):
    sheets: list[str]
    columns: list[str]
    rows: list[dict]
    total_rows: int
    suggested_mapping: dict[str, str | None]


class DashboardImportMappingIn(BaseModel):
    sheet_name: str
    column_mapping: dict[str, str | None]


class DashboardImportOut(BaseModel):
    id: str
    application_id: str | None
    original_filename: str
    sheet_name: str | None
    available_sheets: list[str]
    column_mapping: dict
    status: str
    total_rows: int
    imported_rows: int
    rejected_rows: int
    duplicate_rows: int
    missing_columns: list[str]
    created_at: datetime
    executed_at: datetime | None

    model_config = {"from_attributes": True}


class DashboardImportErrorReport(BaseModel):
    total_rows: int
    imported_rows: int
    rejected_rows: int
    duplicate_rows: int
    missing_columns: list[str]
    errors: list[dict]
