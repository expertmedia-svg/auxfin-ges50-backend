import uuid

import pytest

from app.models.applications import Agent, AgentGroupAssignment, Application
from app.models.dashboard import DashboardImport, DashboardImportRow
from app.models.enums import EvidenceSource, EvidenceType, ProcessingStatus, ReconciliationStatus, SyncStatus
from app.models.evidence import EvidenceExtraction, EvidenceFile
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.services.reconciliation.engine import ReconciliationError, execute_reconciliation_run


def _make_application(db, code="financecoach"):
    app = Application(code=code, name=code.title())
    db.add(app)
    db.flush()
    return app


def _make_evidence(db, application_id, group_id, sync_date, sync_status, requires_review=False, confidence=0.9):
    evidence = EvidenceFile(
        original_filename="preuve.mp4",
        stored_filename=f"{uuid.uuid4().hex}.mp4",
        mime_type="video/mp4",
        media_type=EvidenceType.VIDEO,
        file_size=1000,
        sha256=uuid.uuid4().hex,
        source=EvidenceSource.MANUAL_UPLOAD,
        application_id=application_id,
        processing_status=ProcessingStatus.COMPLETED,
        storage_path="uploads/x.mp4",
    )
    db.add(evidence)
    db.flush()
    extraction = EvidenceExtraction(
        evidence_id=evidence.id,
        normalized_group_id=group_id,
        normalized_date=sync_date,
        sync_status=sync_status,
        requires_manual_review=requires_review,
        global_confidence=confidence,
    )
    db.add(extraction)
    db.flush()
    return evidence


def _make_dashboard_row(db, dashboard_import_id, group_id, sync_date, row_number):
    row = DashboardImportRow(
        dashboard_import_id=dashboard_import_id,
        row_number=row_number,
        raw_group_id=group_id,
        normalized_group_id=group_id,
        sync_date=sync_date,
        is_valid=True,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def scenario(db_session):
    db = db_session
    app = _make_application(db)

    dashboard_import = DashboardImport(
        application_id=app.id, original_filename="dashboard.xlsx", storage_path="dashboard_imports/x.xlsx",
        status="COMPLETED",
    )
    db.add(dashboard_import)
    db.flush()

    # gr1.a : conforme + doublon whatsapp
    _make_dashboard_row(db, dashboard_import.id, "gr1.a", "2026-07-30", 2)
    _make_evidence(db, app.id, "gr1.a", "2026-07-30", SyncStatus.SUCCESS)
    _make_evidence(db, app.id, "gr1.a", "2026-07-30", SyncStatus.SUCCESS)

    # gr2.b : dashboard sans preuve
    _make_dashboard_row(db, dashboard_import.id, "gr2.b", "2026-07-29", 3)

    # gr3.c : doublon dashboard (deux lignes)
    _make_dashboard_row(db, dashboard_import.id, "gr3.c", "2026-07-28", 4)
    _make_dashboard_row(db, dashboard_import.id, "gr3.c", "2026-07-28", 5)

    # gr4.d : declare whatsapp absent du dashboard
    _make_evidence(db, app.id, "gr4.d", "2026-07-27", SyncStatus.SUCCESS)

    # ID illisible
    _make_evidence(db, app.id, None, None, SyncStatus.SUCCESS)

    # Date illisible
    _make_evidence(db, app.id, "gr6.f", None, SyncStatus.SUCCESS)

    # Echec synchronisation
    _make_evidence(db, app.id, "gr7.g", "2026-07-26", SyncStatus.FAILED)

    # Non confirmee
    _make_evidence(db, app.id, "gr8.h", "2026-07-26", SyncStatus.UNCONFIRMED)

    # Verification manuelle
    _make_evidence(db, app.id, "gr9.i", "2026-07-26", SyncStatus.SUCCESS, requires_review=True)

    # Ecart de date
    _make_dashboard_row(db, dashboard_import.id, "gr10.j", "2026-07-01", 6)
    _make_evidence(db, app.id, "gr10.j", "2026-07-05", SyncStatus.SUCCESS)

    db.commit()

    run = ReconciliationRun(application_id=app.id, dashboard_import_id=dashboard_import.id, date_tolerance_days=0)
    db.add(run)
    db.commit()

    return db, run, app, dashboard_import


def _statuses(db, run_id):
    return [r.status for r in db.query(ReconciliationResult).filter(ReconciliationResult.run_id == run_id).all()]


def test_reconciliation_produces_expected_statuses(scenario):
    db, run, _app, _dash = scenario
    run = execute_reconciliation_run(db, run.id)
    statuses = _statuses(db, run.id)

    assert statuses.count(ReconciliationStatus.CONFORME) == 1
    assert statuses.count(ReconciliationStatus.DOUBLON_WHATSAPP) == 1
    assert statuses.count(ReconciliationStatus.DASHBOARD_SANS_PREUVE_WHATSAPP) == 1
    assert statuses.count(ReconciliationStatus.DOUBLON_DASHBOARD) == 2
    assert statuses.count(ReconciliationStatus.DECLARE_WHATSAPP_ABSENT_DASHBOARD) == 1
    assert statuses.count(ReconciliationStatus.ID_ILLISIBLE) == 1
    assert statuses.count(ReconciliationStatus.DATE_ILLISIBLE) == 1
    assert statuses.count(ReconciliationStatus.ECHEC_SYNCHRONISATION) == 1
    assert statuses.count(ReconciliationStatus.SYNCHRONISATION_NON_CONFIRMEE) == 1
    assert statuses.count(ReconciliationStatus.VERIFICATION_MANUELLE) == 1
    assert statuses.count(ReconciliationStatus.ECART_DATE) == 1

    assert run.summary[ReconciliationStatus.CONFORME.value] == 1


def test_reconciliation_without_dashboard_import_raises(db_session):
    app = _make_application(db_session)
    run = ReconciliationRun(application_id=app.id, dashboard_import_id=None)
    db_session.add(run)
    db_session.commit()

    with pytest.raises(ReconciliationError):
        execute_reconciliation_run(db_session, run.id)


def test_id_inconnu_when_not_in_known_groups(db_session):
    db = db_session
    app = _make_application(db)
    dashboard_import = DashboardImport(
        application_id=app.id, original_filename="d.xlsx", storage_path="x", status="COMPLETED"
    )
    db.add(dashboard_import)
    db.flush()

    agent = Agent(full_name="Agent A")
    db.add(agent)
    db.flush()
    db.add(AgentGroupAssignment(agent_id=agent.id, application_id=app.id, group_id="gr1.known"))
    db.flush()

    _make_evidence(db, app.id, "gr99.inconnu", "2026-07-30", SyncStatus.SUCCESS)
    db.commit()

    run = ReconciliationRun(application_id=app.id, dashboard_import_id=dashboard_import.id)
    db.add(run)
    db.commit()

    run = execute_reconciliation_run(db, run.id)
    statuses = _statuses(db, run.id)
    assert ReconciliationStatus.ID_INCONNU in statuses


def test_mauvaise_application_detected(db_session):
    db = db_session
    app_a = _make_application(db, code="financecoach")
    app_b = _make_application(db, code="agricoach")

    dashboard_import_a = DashboardImport(
        application_id=app_a.id, original_filename="d.xlsx", storage_path="x", status="COMPLETED"
    )
    db.add(dashboard_import_a)
    db.flush()

    dashboard_import_b = DashboardImport(
        application_id=app_b.id, original_filename="d2.xlsx", storage_path="y", status="COMPLETED"
    )
    db.add(dashboard_import_b)
    db.flush()

    # L'ID existe dans le dashboard de l'application B, pas A.
    _make_dashboard_row(db, dashboard_import_b.id, "gr5.shared", "2026-07-30", 2)
    _make_evidence(db, app_a.id, "gr5.shared", "2026-07-30", SyncStatus.SUCCESS)
    db.commit()

    run = ReconciliationRun(application_id=app_a.id, dashboard_import_id=dashboard_import_a.id)
    db.add(run)
    db.commit()

    run = execute_reconciliation_run(db, run.id)
    statuses = _statuses(db, run.id)
    assert ReconciliationStatus.MAUVAISE_APPLICATION in statuses
