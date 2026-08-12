"""Execution reelle de l'import des exports dashboard : lecture du fichier
selon le mapping choisi, normalisation ID/date, detection des doublons et
rapport d'erreurs ligne par ligne (section 7). Aucune ligne invalide n'est
supprimee silencieusement : elle est conservee avec ses erreurs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.dashboard import DashboardImport, DashboardImportRow
from app.services.excel_import.sheet_inspector import read_sheet
from app.services.vision.date_parser import parse_date
from app.services.vision.id_normalizer import normalize_group_id


class DashboardImportError(Exception):
    pass


def execute_dashboard_import(db: Session, dashboard_import_id: str) -> DashboardImport:
    dashboard_import = db.get(DashboardImport, dashboard_import_id)
    if dashboard_import is None:
        raise DashboardImportError(f"Import introuvable: {dashboard_import_id}")

    mapping = dashboard_import.column_mapping
    if not mapping or not mapping.get("group_id"):
        raise DashboardImportError(
            "Le mapping de colonnes doit au minimum associer l'ID du groupe avant l'execution"
        )

    from app.services.storage.storage_service import get_storage_service

    file_path = str(get_storage_service().resolve(dashboard_import.storage_path))
    df = read_sheet(file_path, dashboard_import.sheet_name)

    missing_columns = [
        field
        for field, column in mapping.items()
        if column and column not in df.columns
    ]

    db.query(DashboardImportRow).filter(
        DashboardImportRow.dashboard_import_id == dashboard_import.id
    ).delete()

    seen_ids: dict[str, int] = {}
    imported = 0
    rejected = 0
    duplicates = 0
    error_report: list[dict] = []

    group_col = mapping.get("group_id")
    declared_col = mapping.get("declared_group_id")
    date_col = mapping.get("sync_date")
    agent_col = mapping.get("agent")
    locality_col = mapping.get("locality")
    status_col = mapping.get("status")

    for idx, series in df.iterrows():
        row_number = idx + 2  # +1 pour 0-index, +1 pour la ligne d'en-tete
        raw_id = str(series.get(group_col, "")).strip() if group_col else ""
        validation_errors: list[str] = []

        normalized_id = None
        if not raw_id:
            validation_errors.append("ID du groupe manquant")
        else:
            norm_result = normalize_group_id(raw_id)
            normalized_id = norm_result.normalized
            if not normalized_id:
                validation_errors.append(f"Format d'ID de groupe invalide: '{raw_id}'")

        declared_id = str(series.get(declared_col, "")).strip() if declared_col else None

        raw_date_value = str(series.get(date_col, "")).strip() if date_col else ""
        normalized_date = None
        if date_col and not raw_date_value:
            validation_errors.append("Date de synchronisation manquante")
        elif raw_date_value:
            date_result = parse_date(raw_date_value)
            normalized_date = date_result.normalized_date
            if not normalized_date:
                validation_errors.append(f"Date illisible ou incomplete: '{raw_date_value}'")

        is_duplicate = False
        if normalized_id:
            if normalized_id in seen_ids:
                is_duplicate = True
                duplicates += 1
            else:
                seen_ids[normalized_id] = row_number

        is_valid = not validation_errors
        if is_valid:
            imported += 1
        else:
            rejected += 1
            error_report.append({"row": row_number, "raw_id": raw_id, "errors": validation_errors})

        db.add(
            DashboardImportRow(
                dashboard_import_id=dashboard_import.id,
                row_number=row_number,
                raw_group_id=raw_id or None,
                normalized_group_id=normalized_id,
                declared_group_id=declared_id or None,
                sync_date_raw=raw_date_value or None,
                sync_date=normalized_date,
                agent_name=str(series.get(agent_col, "")).strip() or None if agent_col else None,
                locality=str(series.get(locality_col, "")).strip() or None if locality_col else None,
                status_raw=str(series.get(status_col, "")).strip() or None if status_col else None,
                is_valid=is_valid,
                validation_errors=validation_errors,
                is_duplicate=is_duplicate,
            )
        )

    dashboard_import.total_rows = len(df)
    dashboard_import.imported_rows = imported
    dashboard_import.rejected_rows = rejected
    dashboard_import.duplicate_rows = duplicates
    dashboard_import.missing_columns = missing_columns
    dashboard_import.error_report = error_report[:1000]
    dashboard_import.status = "COMPLETED"
    dashboard_import.executed_at = datetime.now(UTC)

    db.commit()
    db.refresh(dashboard_import)
    return dashboard_import
