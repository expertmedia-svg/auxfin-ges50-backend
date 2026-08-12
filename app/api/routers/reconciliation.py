from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES, WRITE_ROLES
from app.models.identity import User
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.schemas.reconciliation import ReconciliationResultOut, ReconciliationRunCreate, ReconciliationRunOut
from app.services.reconciliation.engine import ReconciliationError, execute_reconciliation_run

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.post("/run", response_model=ReconciliationRunOut, status_code=status.HTTP_201_CREATED)
def create_and_run(
    payload: ReconciliationRunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> ReconciliationRun:
    run = ReconciliationRun(
        application_id=payload.application_id,
        dashboard_import_id=payload.dashboard_import_id,
        date_tolerance_days=payload.date_tolerance_days,
        period_start=payload.period_start,
        period_end=payload.period_end,
        triggered_by_id=user.id,
        status="PENDING",
    )
    db.add(run)
    db.flush()

    try:
        run = execute_reconciliation_run(db, run.id)
    except ReconciliationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        record_audit(db, user_id=user.id, action="reconciliation.run", entity_id=run.id)
        db.commit()

    db.refresh(run)
    return run


@router.get("/results", response_model=list[ReconciliationResultOut])
def get_results(
    run_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    application_id: str | None = None,
    agent_id: str | None = None,
    group_id: str | None = None,
    locality: str | None = None,
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[ReconciliationResult]:
    query = db.query(ReconciliationResult).filter(ReconciliationResult.run_id == run_id)
    if status_filter:
        query = query.filter(ReconciliationResult.status == status_filter)
    if application_id:
        query = query.filter(ReconciliationResult.application_id == application_id)
    if agent_id:
        query = query.filter(ReconciliationResult.agent_id == agent_id)
    if locality:
        query = query.filter(ReconciliationResult.locality == locality)
    if group_id:
        query = query.filter(
            (ReconciliationResult.whatsapp_group_id == group_id)
            | (ReconciliationResult.dashboard_group_id == group_id)
        )
    return query.offset(offset).limit(limit).all()


@router.get("/summary", response_model=ReconciliationRunOut)
def get_summary(
    run_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> ReconciliationRun:
    run = db.get(ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rapprochement introuvable")
    return run


@router.get("/runs", response_model=list[ReconciliationRunOut])
def list_runs(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[ReconciliationRun]:
    return db.query(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(50).all()
