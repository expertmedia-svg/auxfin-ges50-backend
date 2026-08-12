import shutil
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import READ_ROLES
from app.models.enums import JobStatus
from app.models.evidence import ProcessingJob
from app.models.identity import User

router = APIRouter(prefix="/system", tags=["system"])
settings = get_settings()


def _check_database(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _check_broker() -> dict:
    """Verifie le broker Celery reellement configure (filesystem:// sans
    Docker/Redis, ou redis:// en production Linux native) — pas Redis en dur,
    la verification doit refleter CELERY_BROKER_URL quel qu'il soit."""
    broker_url = settings.celery_broker_url
    if broker_url.startswith("filesystem://"):
        broker_dir = settings.celery_filesystem_broker_dir / "out"
        if broker_dir.is_dir():
            return {"status": "ok", "type": "filesystem", "path": str(broker_dir)}
        return {"status": "error", "type": "filesystem", "detail": f"Dossier introuvable: {broker_dir}"}

    try:
        import redis

        client = redis.Redis.from_url(broker_url, socket_connect_timeout=1.5, socket_timeout=1.5)
        client.ping()
        return {"status": "ok", "type": "redis"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "type": "redis", "detail": str(exc)}


def _check_worker() -> dict:
    try:
        from app.workers.celery_app import celery_app

        pong = celery_app.control.ping(timeout=1.0)
        if pong:
            return {"status": "ok", "workers": len(pong)}
        return {"status": "error", "detail": "Aucun worker Celery ne repond"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _disk_usage() -> dict:
    usage = shutil.disk_usage(settings.storage_root)
    return {
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
    }


@router.get("/health")
def system_health(db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))) -> dict:
    pending_jobs = db.query(ProcessingJob).filter(
        ProcessingJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.PROCESSING])
    ).count()
    last_failures = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status == JobStatus.FAILED)
        .order_by(ProcessingJob.finished_at.desc())
        .limit(10)
        .all()
    )

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "api": {"status": "ok"},
        "database": _check_database(db),
        "broker": _check_broker(),
        "worker": _check_worker(),
        "disk": _disk_usage(),
        "pending_jobs": pending_jobs,
        "last_failures": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "error": j.error_message,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in last_failures
        ],
        "app_version": "0.1.0",
    }
