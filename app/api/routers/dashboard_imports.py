import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.models.dashboard import DashboardImport
from app.models.identity import User
from app.schemas.dashboard_imports import (
    DashboardImportErrorReport,
    DashboardImportMappingIn,
    DashboardImportOut,
    DashboardImportPreview,
)
from app.services.excel_import.import_service import DashboardImportError, execute_dashboard_import
from app.services.excel_import.sheet_inspector import list_sheets, preview_sheet, suggest_column_mapping
from app.services.storage.storage_service import get_storage_service

router = APIRouter(prefix="/dashboard-imports", tags=["dashboard-imports"])

ALLOWED_EXTENSIONS = (".xlsx", ".xls", ".csv")


@router.post("/preview", response_model=DashboardImportPreview)
def preview_dashboard_file(
    file: UploadFile = File(...), _: User = Depends(require_roles(*WRITE_ROLES))
) -> DashboardImportPreview:
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Format non supporte (xlsx, xls, csv)")

    tmp_path = Path(tempfile.mkdtemp(prefix="ges_g50_dash_preview_")) / file.filename
    with open(tmp_path, "wb") as f:
        f.write(file.file.read())

    try:
        sheets = list_sheets(str(tmp_path))
        first_sheet = sheets[0] if sheets else None
        data = preview_sheet(str(tmp_path), first_sheet)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Impossible de lire le fichier: {exc}") from exc

    return DashboardImportPreview(
        sheets=sheets,
        columns=data["columns"],
        rows=data["rows"],
        total_rows=data["total_rows"],
        suggested_mapping=suggest_column_mapping(data["columns"]),
    )


@router.post("", response_model=DashboardImportOut, status_code=status.HTTP_201_CREATED)
def create_dashboard_import(
    file: UploadFile = File(...),
    application_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> DashboardImport:
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Format non supporte (xlsx, xls, csv)")

    tmp_path = Path(tempfile.mkdtemp(prefix="ges_g50_dash_")) / file.filename
    with open(tmp_path, "wb") as f:
        f.write(file.file.read())

    storage_path = get_storage_service().save(tmp_path, subdirectory="dashboard_imports")
    sheets = list_sheets(str(tmp_path))

    dashboard_import = DashboardImport(
        application_id=application_id,
        original_filename=file.filename,
        storage_path=storage_path,
        available_sheets=sheets,
        sheet_name=sheets[0] if sheets else None,
        column_mapping=suggest_column_mapping(preview_sheet(str(tmp_path), sheets[0] if sheets else None)["columns"]),
        status="PENDING",
        uploaded_by_id=user.id,
    )
    db.add(dashboard_import)
    record_audit(db, user_id=user.id, action="dashboard_import.create", details={"filename": file.filename})
    db.commit()
    db.refresh(dashboard_import)
    return dashboard_import


@router.get("", response_model=list[DashboardImportOut])
def list_dashboard_imports(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[DashboardImport]:
    return db.query(DashboardImport).order_by(DashboardImport.created_at.desc()).all()


@router.get("/{import_id}", response_model=DashboardImportOut)
def get_dashboard_import(
    import_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> DashboardImport:
    dashboard_import = db.get(DashboardImport, import_id)
    if dashboard_import is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import introuvable")
    return dashboard_import


@router.put("/{import_id}/mapping", response_model=DashboardImportOut)
def update_mapping(
    import_id: str,
    payload: DashboardImportMappingIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> DashboardImport:
    dashboard_import = db.get(DashboardImport, import_id)
    if dashboard_import is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import introuvable")
    dashboard_import.sheet_name = payload.sheet_name
    dashboard_import.column_mapping = payload.column_mapping
    record_audit(db, user_id=user.id, action="dashboard_import.mapping", entity_id=import_id)
    db.commit()
    db.refresh(dashboard_import)
    return dashboard_import


@router.post("/{import_id}/execute", response_model=DashboardImportErrorReport)
def execute_import(
    import_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))
) -> DashboardImportErrorReport:
    try:
        dashboard_import = execute_dashboard_import(db, import_id)
    except DashboardImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record_audit(
        db, user_id=user.id, action="dashboard_import.execute", entity_id=import_id,
        details={"imported_rows": dashboard_import.imported_rows, "rejected_rows": dashboard_import.rejected_rows},
    )
    db.commit()

    return DashboardImportErrorReport(
        total_rows=dashboard_import.total_rows,
        imported_rows=dashboard_import.imported_rows,
        rejected_rows=dashboard_import.rejected_rows,
        duplicate_rows=dashboard_import.duplicate_rows,
        missing_columns=dashboard_import.missing_columns,
        errors=dashboard_import.error_report,
    )
