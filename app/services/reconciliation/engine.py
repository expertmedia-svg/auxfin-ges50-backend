"""Moteur de rapprochement : compare les preuves WhatsApp (evidence_extractions)
aux lignes du dashboard importe (dashboard_import_rows) sur application + ID
normalise + date, avec tolerance configurable, et produit les 13 statuts du
cahier des charges (section 13). Priorite appliquee par preuve, du probleme le
plus bloquant (ID illisible) au rapprochement effectif (conforme / ecart)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.applications import AgentGroupAssignment
from app.models.dashboard import DashboardImport, DashboardImportRow
from app.models.enums import ProcessingStatus, ReconciliationStatus, SyncStatus
from app.models.evidence import EvidenceExtraction, EvidenceFile
from app.models.reconciliation import ReconciliationResult, ReconciliationRun


class ReconciliationError(Exception):
    pass


@dataclass
class _WhatsAppEntry:
    evidence_id: str
    application_id: str | None
    group_id: str | None
    sync_date: str | None
    sync_status: SyncStatus
    requires_manual_review: bool
    confidence: float
    agent_id: str | None


def _date_within_tolerance(d1: str | None, d2: str | None, tolerance_days: int) -> bool:
    if not d1 or not d2:
        return False
    try:
        parsed1 = datetime.fromisoformat(d1).date()
        parsed2 = datetime.fromisoformat(d2).date()
    except ValueError:
        return False
    return abs((parsed1 - parsed2).days) <= tolerance_days


def execute_reconciliation_run(db: Session, run_id: str) -> ReconciliationRun:
    run = db.get(ReconciliationRun, run_id)
    if run is None:
        raise ReconciliationError(f"Rapprochement introuvable: {run_id}")

    if not run.dashboard_import_id:
        run.status = "FAILED"
        run.summary = {"error": "Aucun fichier dashboard reel selectionne pour ce rapprochement"}
        db.commit()
        raise ReconciliationError(
            "Aucune donnee dashboard disponible : deposez un export reel avant de lancer le rapprochement"
        )

    dashboard_import = db.get(DashboardImport, run.dashboard_import_id)
    if dashboard_import is None or dashboard_import.status != "COMPLETED":
        run.status = "FAILED"
        run.summary = {"error": "L'import dashboard selectionne n'a pas ete execute avec succes"}
        db.commit()
        raise ReconciliationError("Import dashboard invalide ou non execute")

    run.status = "PROCESSING"
    run.started_at = datetime.now(UTC)
    db.flush()

    db.query(ReconciliationResult).filter(ReconciliationResult.run_id == run.id).delete()

    whatsapp_entries = _collect_whatsapp_entries(db, run)
    dashboard_query = (
        db.query(DashboardImportRow)
        .filter(DashboardImportRow.dashboard_import_id == dashboard_import.id, DashboardImportRow.is_valid.is_(True))
    )
    if run.period_start:
        dashboard_query = dashboard_query.filter(DashboardImportRow.sync_date >= run.period_start)
    if run.period_end:
        dashboard_query = dashboard_query.filter(DashboardImportRow.sync_date <= run.period_end)
    dashboard_rows = dashboard_query.all()

    # IDs connus pour d'autres applications (detection MAUVAISE_APPLICATION).
    other_app_ids: set[str] = set()
    if run.application_id:
        rows_other_apps = (
            db.query(DashboardImportRow.normalized_group_id)
            .join(DashboardImportRow.dashboard_import)
            .filter(
                DashboardImportRow.dashboard_import.has(DashboardImport.application_id != run.application_id),
                DashboardImportRow.normalized_group_id.isnot(None),
            )
            .all()
        )
        other_app_ids = {r[0] for r in rows_other_apps}

    all_identified_whatsapp_ids = {e.group_id for e in whatsapp_entries if e.group_id}

    # Reference des groupes reellement assignes aux agents pour cette application,
    # quand elle est renseignee (section K), pour distinguer un ID simplement
    # absent de cet export d'un ID qui ne correspond a aucun groupe connu.
    known_group_ids: set[str] = set()
    if run.application_id:
        assignments = (
            db.query(AgentGroupAssignment.group_id)
            .filter(AgentGroupAssignment.application_id == run.application_id)
            .all()
        )
        known_group_ids = {a[0] for a in assignments}

    results: list[ReconciliationResult] = []
    seen_wa_ids_this_run: dict[tuple, int] = defaultdict(int)

    for entry in whatsapp_entries:
        status, dashboard_group_id, dashboard_date, dashboard_row_id = _classify_whatsapp_entry(
            entry, dashboard_rows, other_app_ids, known_group_ids, seen_wa_ids_this_run, run.date_tolerance_days
        )
        results.append(
            ReconciliationResult(
                run_id=run.id,
                application_id=entry.application_id,
                status=status,
                whatsapp_group_id=entry.group_id,
                dashboard_group_id=dashboard_group_id,
                whatsapp_date=entry.sync_date,
                dashboard_date=dashboard_date,
                evidence_id=entry.evidence_id,
                dashboard_import_row_id=dashboard_row_id,
                agent_id=entry.agent_id,
                confidence=entry.confidence,
            )
        )

    dashboard_id_counts: dict[tuple, int] = defaultdict(int)
    for row in dashboard_rows:
        if row.normalized_group_id:
            dashboard_id_counts[row.normalized_group_id, row.sync_date] += 1

    for row in dashboard_rows:
        if not row.normalized_group_id:
            continue
        if row.normalized_group_id not in all_identified_whatsapp_ids:
            status = (
                ReconciliationStatus.DOUBLON_DASHBOARD
                if dashboard_id_counts[row.normalized_group_id, row.sync_date] > 1
                else ReconciliationStatus.DASHBOARD_SANS_PREUVE_WHATSAPP
            )
            results.append(
                ReconciliationResult(
                    run_id=run.id,
                    application_id=run.application_id,
                    status=status,
                    dashboard_group_id=row.normalized_group_id,
                    dashboard_date=row.sync_date,
                    locality=row.locality,
                    dashboard_import_row_id=row.id,
                )
            )

    db.add_all(results)

    summary: dict[str, int] = defaultdict(int)
    for result in results:
        summary[result.status.value if hasattr(result.status, "value") else result.status] += 1

    run.summary = dict(summary)
    run.status = "COMPLETED"
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def _collect_whatsapp_entries(db: Session, run: ReconciliationRun) -> list[_WhatsAppEntry]:
    query = (
        db.query(EvidenceExtraction, EvidenceFile)
        .join(EvidenceFile, EvidenceExtraction.evidence_id == EvidenceFile.id)
        .filter(EvidenceFile.processing_status.in_([ProcessingStatus.COMPLETED, ProcessingStatus.REQUIRES_REVIEW]))
        .filter(EvidenceFile.is_duplicate_of_id.is_(None))
    )
    if run.application_id:
        query = query.filter(EvidenceFile.application_id == run.application_id)
    report_date = func.coalesce(EvidenceExtraction.manually_corrected_date, EvidenceExtraction.normalized_date)
    if run.period_start:
        query = query.filter(or_(report_date >= run.period_start,
                                 and_(report_date.is_(None), EvidenceFile.received_at >=
                                      datetime.fromisoformat(run.period_start))))
    if run.period_end:
        query = query.filter(or_(report_date <= run.period_end,
                                 and_(report_date.is_(None), EvidenceFile.received_at <
                                      datetime.fromisoformat(run.period_end) + timedelta(days=1))))

    entries: list[_WhatsAppEntry] = []
    for extraction, evidence in query.all():
        entries.append(
            _WhatsAppEntry(
                evidence_id=evidence.id,
                application_id=evidence.application_id,
                group_id=extraction.effective_group_id,
                sync_date=extraction.effective_date,
                sync_status=extraction.sync_status,
                requires_manual_review=(extraction.requires_manual_review or extraction.date_is_ambiguous
                                        or not evidence.application_id
                                        or evidence.processing_status != ProcessingStatus.COMPLETED),
                confidence=extraction.global_confidence,
                agent_id=evidence.agent_id,
            )
        )
    return entries


def _classify_whatsapp_entry(
    entry: _WhatsAppEntry,
    dashboard_rows: list[DashboardImportRow],
    other_app_ids: set[str],
    known_group_ids: set[str],
    seen_ids: dict[tuple, int],
    tolerance_days: int,
) -> tuple[ReconciliationStatus, str | None, str | None, str | None]:
    if not entry.group_id:
        return ReconciliationStatus.ID_ILLISIBLE, None, None, None

    if not entry.sync_date:
        return ReconciliationStatus.DATE_ILLISIBLE, None, None, None

    if entry.sync_status == SyncStatus.FAILED:
        return ReconciliationStatus.ECHEC_SYNCHRONISATION, None, None, None

    if entry.sync_status == SyncStatus.UNCONFIRMED:
        return ReconciliationStatus.SYNCHRONISATION_NON_CONFIRMEE, None, None, None

    if entry.requires_manual_review:
        return ReconciliationStatus.VERIFICATION_MANUELLE, None, None, None

    matching_rows = [r for r in dashboard_rows if r.normalized_group_id == entry.group_id
                     and r.dashboard_import.application_id in (None, entry.application_id)]

    if not matching_rows and entry.group_id in other_app_ids:
        return ReconciliationStatus.MAUVAISE_APPLICATION, None, None, None

    key = (entry.application_id, entry.group_id, entry.sync_date)
    seen_ids[key] += 1
    if seen_ids[key] > 1:
        return ReconciliationStatus.DOUBLON_WHATSAPP, None, None, None

    if not matching_rows:
        if known_group_ids and entry.group_id not in known_group_ids:
            return ReconciliationStatus.ID_INCONNU, None, None, None
        return ReconciliationStatus.DECLARE_WHATSAPP_ABSENT_DASHBOARD, None, None, None

    # Plusieurs périodes peuvent exister pour un même groupe dans l'export.
    def distance(row):
        try:
            return abs((datetime.fromisoformat(entry.sync_date) - datetime.fromisoformat(row.sync_date)).days)
        except (ValueError, TypeError):
            return float("inf")
    best_row = min(matching_rows, key=distance)
    if entry.sync_date == best_row.sync_date:
        return ReconciliationStatus.CONFORME, best_row.normalized_group_id, best_row.sync_date, best_row.id
    if _date_within_tolerance(entry.sync_date, best_row.sync_date, tolerance_days):
        return ReconciliationStatus.CONFORME, best_row.normalized_group_id, best_row.sync_date, best_row.id
    return ReconciliationStatus.ECART_DATE, best_row.normalized_group_id, best_row.sync_date, best_row.id
