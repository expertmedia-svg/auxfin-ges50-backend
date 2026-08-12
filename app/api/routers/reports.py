from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.models.identity import User
from app.models.system import Report
from app.schemas.reports import ReportCreate, ReportOut
from app.services.reports.generator import ReportGenerationError, generate_report
from app.services.storage.storage_service import get_storage_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportOut])
def list_reports(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[Report]:
    return db.query(Report).order_by(Report.created_at.desc()).limit(100).all()


@router.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def generate(
    payload: ReportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> Report:
    report = Report(
        report_type=payload.report_type,
        format=payload.format,
        period_start=payload.period_start,
        period_end=payload.period_end,
        application_id=payload.application_id,
        reconciliation_run_id=payload.reconciliation_run_id,
        status="PENDING",
        requested_by_id=user.id,
    )
    db.add(report)
    db.flush()

    try:
        generate_report(db, report.id)
    except ReportGenerationError as exc:
        record_audit(db, user_id=user.id, action="report.generate_failed", entity_id=report.id, details={"error": str(exc)})
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record_audit(db, user_id=user.id, action="report.generate", entity_id=report.id)
    db.commit()
    db.refresh(report)
    return report


@router.get("/{report_id}/download")
def download_report(
    report_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> FileResponse:
    report = db.get(Report, report_id)
    if report is None or report.status != "COMPLETED" or not report.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rapport introuvable ou non genere")
    path = get_storage_service().resolve(report.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier de rapport introuvable sur le stockage")
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    media_type = "application/pdf" if report.format == "pdf" else xlsx_type
    return FileResponse(str(path), media_type=media_type, filename=path.name)
