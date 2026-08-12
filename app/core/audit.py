from sqlalchemy.orm import Session

from app.models.system import AuditLog


def record_audit(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    correlation_id: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        ip_address=ip_address,
        correlation_id=correlation_id,
    )
    db.add(entry)
    db.flush()
    return entry
