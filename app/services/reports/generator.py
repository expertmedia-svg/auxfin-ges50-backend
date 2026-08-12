"""Generation reelle des rapports (Excel multi-feuilles section 16, PDF de
synthese). Si aucune donnee de rapprochement reelle n'existe pour le
perimetre demande, le rapport echoue explicitement plutot que de produire un
fichier vide ou invente."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.dashboard import DashboardImportRow
from app.models.enums import ReconciliationStatus
from app.models.evidence import EvidenceExtraction, EvidenceFile
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.models.system import Report
from app.services.reports.excel_builder import write_sheet
from app.services.storage.storage_service import get_storage_service

settings = get_settings()

_STATUS_GROUPS: dict[str, list[ReconciliationStatus]] = {
    "Correspondances": [ReconciliationStatus.CONFORME],
    "WhatsApp absents du dashboard": [ReconciliationStatus.DECLARE_WHATSAPP_ABSENT_DASHBOARD],
    "Dashboard sans preuve WhatsApp": [ReconciliationStatus.DASHBOARD_SANS_PREUVE_WHATSAPP],
    "Ecarts de date": [ReconciliationStatus.ECART_DATE],
    "Doublons WhatsApp": [ReconciliationStatus.DOUBLON_WHATSAPP],
    "Doublons dashboard": [ReconciliationStatus.DOUBLON_DASHBOARD],
    "Synchronisations echouees": [ReconciliationStatus.ECHEC_SYNCHRONISATION],
    "Preuves illisibles": [ReconciliationStatus.ID_ILLISIBLE, ReconciliationStatus.DATE_ILLISIBLE],
    "Verifications manuelles": [
        ReconciliationStatus.VERIFICATION_MANUELLE,
        ReconciliationStatus.SYNCHRONISATION_NON_CONFIRMEE,
        ReconciliationStatus.ID_INCONNU,
        ReconciliationStatus.MAUVAISE_APPLICATION,
    ],
}


class ReportGenerationError(Exception):
    pass


def _find_run(db: Session, report: Report) -> ReconciliationRun | None:
    if report.reconciliation_run_id:
        return db.get(ReconciliationRun, report.reconciliation_run_id)
    query = db.query(ReconciliationRun).filter(ReconciliationRun.status == "COMPLETED")
    if report.application_id:
        query = query.filter(ReconciliationRun.application_id == report.application_id)
    return query.order_by(ReconciliationRun.finished_at.desc()).first()


def generate_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise ReportGenerationError(f"Rapport introuvable: {report_id}")

    run = _find_run(db, report)
    if run is None:
        report.status = "FAILED"
        report.error_message = (
            "Aucune donnee disponible : aucun rapprochement reel n'a ete execute pour ce perimetre"
        )
        db.commit()
        raise ReportGenerationError(report.error_message)

    try:
        if report.format == "pdf":
            path = _generate_pdf(report, run, db)
        else:
            path = _generate_excel(report, run, db)

        storage = get_storage_service()
        storage_path = storage.save(path, subdirectory="reports")
        report.storage_path = storage_path
        report.status = "COMPLETED"
        report.generated_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001
        report.status = "FAILED"
        report.error_message = str(exc)
        raise
    finally:
        db.commit()
        db.refresh(report)

    return report


def _results_for(db: Session, run_id: str, statuses: list[ReconciliationStatus]) -> list[ReconciliationResult]:
    return (
        db.query(ReconciliationResult)
        .filter(ReconciliationResult.run_id == run_id, ReconciliationResult.status.in_(statuses))
        .all()
    )


def _result_row(r: ReconciliationResult) -> list:
    return [
        r.whatsapp_group_id or "",
        r.dashboard_group_id or "",
        r.whatsapp_date or "",
        r.dashboard_date or "",
        r.status.value if hasattr(r.status, "value") else r.status,
        r.confidence or 0,
        r.locality or "",
        r.comment or "",
    ]


_RESULT_HEADERS = [
    "ID WhatsApp", "ID Dashboard", "Date WhatsApp", "Date Dashboard",
    "Statut", "Confiance", "Localite", "Commentaire",
]


def _generate_excel(report: Report, run: ReconciliationRun, db: Session) -> Path:
    wb = Workbook()
    wb.remove(wb.active)

    all_results = db.query(ReconciliationResult).filter(ReconciliationResult.run_id == run.id).all()
    total = len(all_results) or 1
    summary_rows = []
    for status, count in (run.summary or {}).items():
        summary_rows.append([status, count, round(count / total * 100, 1)])

    ws_summary: Worksheet = wb.create_sheet("Synthese")
    ws_summary.append(["GES G50 - Rapport de rapprochement"])
    ws_summary.append([f"Genere le: {datetime.now(UTC).isoformat()}"])
    ws_summary.append([f"Rapprochement ID: {run.id}"])
    ws_summary.append([])
    ws_summary.append(["Statut", "Nombre", "Pourcentage"])
    for row in summary_rows:
        ws_summary.append(row)

    for group_name, statuses in _STATUS_GROUPS.items():
        rows = [_result_row(r) for r in _results_for(db, run.id, statuses)]
        write_sheet(wb, group_name, _RESULT_HEADERS, rows, status_column=5)

    whatsapp_raw = (
        db.query(EvidenceExtraction, EvidenceFile)
        .join(EvidenceFile, EvidenceExtraction.evidence_id == EvidenceFile.id)
        .all()
    )
    whatsapp_rows = [
        [
            e.raw_group_id or "", e.normalized_group_id or "", e.raw_date or "", e.normalized_date or "",
            e.sync_status.value if hasattr(e.sync_status, "value") else e.sync_status,
            e.global_confidence, ev.original_filename, ev.received_at.isoformat() if ev.received_at else "",
        ]
        for e, ev in whatsapp_raw
    ]
    write_sheet(
        wb, "Donnees brutes WhatsApp",
        ["ID brut", "ID normalise", "Date brute", "Date normalisee", "Statut sync", "Confiance", "Fichier", "Recu le"],
        whatsapp_rows,
    )

    dashboard_rows_data = (
        db.query(DashboardImportRow)
        .filter(DashboardImportRow.dashboard_import_id == run.dashboard_import_id)
        .all()
    )
    dashboard_rows = [
        [
            r.row_number, r.raw_group_id or "", r.normalized_group_id or "", r.sync_date_raw or "",
            r.sync_date or "", r.agent_name or "", r.locality or "", "Oui" if r.is_valid else "Non",
        ]
        for r in dashboard_rows_data
    ]
    write_sheet(
        wb, "Donnees brutes dashboard",
        ["Ligne", "ID brut", "ID normalise", "Date brute", "Date normalisee", "Agent", "Localite", "Valide"],
        dashboard_rows,
    )

    corrections_rows = [
        [
            e.evidence_id, e.normalized_group_id or "", e.manually_corrected_group_id or "",
            e.normalized_date or "", e.manually_corrected_date or "",
            e.manually_corrected_at.isoformat() if e.manually_corrected_at else "",
        ]
        for e, _ in whatsapp_raw
        if e.manually_corrected_group_id or e.manually_corrected_date
    ]
    write_sheet(
        wb, "Historique des corrections",
        ["Preuve", "ID auto", "ID corrige", "Date auto", "Date corrigee", "Corrige le"],
        corrections_rows,
    )

    output_dir = settings.reports_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rapport_{report.id}.xlsx"
    wb.save(output_path)
    return output_path


def _generate_pdf(report: Report, run: ReconciliationRun, db: Session) -> Path:
    output_dir = settings.reports_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rapport_{report.id}.pdf"

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    story = [
        Paragraph("GES G50 - Rapport de rapprochement", styles["Title"]),
        Paragraph(f"Genere le {datetime.now(UTC).strftime('%d/%m/%Y %H:%M')} UTC", styles["Normal"]),
        Spacer(1, 16),
    ]

    total = sum((run.summary or {}).values()) or 1
    table_data = [["Statut", "Nombre", "%"]]
    for status, count in (run.summary or {}).items():
        table_data.append([status, str(count), f"{round(count / total * 100, 1)}%"])

    table = Table(table_data, colWidths=[260, 80, 60])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return output_path
