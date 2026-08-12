from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import RoleCode
from app.models.identity import User
from app.models.system import AuditLog
from app.schemas.audit import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    action: str | None = None,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(
        require_roles(
            RoleCode.SUPER_ADMIN, RoleCode.ADMIN, RoleCode.SUPERVISEUR
        )
    ),
) -> list[AuditLog]:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()
