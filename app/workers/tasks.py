import logging

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="evidence.process", bind=True, max_retries=2)
def process_evidence_task(self, evidence_id: str) -> dict:
    from app.services.evidence_processing import process_evidence

    db = SessionLocal()
    try:
        evidence = process_evidence(db, evidence_id)
        # processing_status est mappee en String(30) simple (pas un type Enum
        # SQLAlchemy) : apres relecture depuis la base, c'est deja une chaine
        # brute, jamais une instance ProcessingStatus. Bug reel trouve en
        # Phase C (le worker echouait silencieusement sur .value apres avoir
        # correctement termine le traitement).
        return {"evidence_id": evidence_id, "status": str(evidence.processing_status)}
    finally:
        db.close()


@celery_app.task(name="dashboard_import.execute")
def execute_dashboard_import_task(dashboard_import_id: str) -> dict:
    from app.services.excel_import.import_service import execute_dashboard_import

    db = SessionLocal()
    try:
        report = execute_dashboard_import(db, dashboard_import_id)
        return {"dashboard_import_id": dashboard_import_id, "imported_rows": report.imported_rows}
    finally:
        db.close()


@celery_app.task(name="reconciliation.run")
def run_reconciliation_task(run_id: str) -> dict:
    from app.services.reconciliation.engine import execute_reconciliation_run

    db = SessionLocal()
    try:
        run = execute_reconciliation_run(db, run_id)
        return {"run_id": run_id, "status": run.status}
    finally:
        db.close()


@celery_app.task(name="reports.generate")
def generate_report_task(report_id: str) -> dict:
    from app.services.reports.generator import generate_report

    db = SessionLocal()
    try:
        report = generate_report(db, report_id)
        return {"report_id": report_id, "status": report.status}
    finally:
        db.close()
