import openpyxl
import pytest

import app.services.storage.storage_service as storage_module
from app.models.dashboard import DashboardImport, DashboardImportRow
from app.services.excel_import.import_service import DashboardImportError, execute_dashboard_import
from app.services.excel_import.sheet_inspector import list_sheets, suggest_column_mapping
from app.services.storage.storage_service import LocalDiskStorage


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "_instance", LocalDiskStorage(tmp_path))
    yield


def _build_sample_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["GR plateforme", "Date synchro", "Agent", "Localite"])
    ws.append(["gr1.loumbila-nonguestenga", "30/07/2026", "Jean O.", "Loumbila"])
    ws.append(["gr2.karangasso-sambla-sembleni", "29/07/2026", "Awa T.", "Karangasso"])
    ws.append(["gr1.loumbila-nonguestenga", "30/07/2026", "Jean O.", "Loumbila"])  # doublon
    ws.append(["", "30/07/2026", "Marc D.", "Bobo"])  # id manquant -> rejetee
    ws.append(["gr4.mal-forme sans slug", "date-invalide", "X", "Y"])  # id + date invalides
    wb.save(path)


def test_list_sheets_and_mapping_suggestion(tmp_path):
    file_path = tmp_path / "dashboard.xlsx"
    _build_sample_workbook(file_path)

    sheets = list_sheets(str(file_path))
    assert sheets == ["Export"]

    mapping = suggest_column_mapping(["GR plateforme", "Date synchro", "Agent", "Localite"])
    assert mapping["group_id"] == "GR plateforme"
    assert mapping["sync_date"] == "Date synchro"
    assert mapping["agent"] == "Agent"
    assert mapping["locality"] == "Localite"


def test_execute_dashboard_import_reports_rows_correctly(db_session, tmp_path):
    file_path = tmp_path / "dashboard.xlsx"
    _build_sample_workbook(file_path)

    storage_path = storage_module.get_storage_service().save(file_path, subdirectory="dashboard_imports")

    dashboard_import = DashboardImport(
        original_filename="dashboard.xlsx",
        storage_path=storage_path,
        sheet_name="Export",
        column_mapping={"group_id": "GR plateforme", "sync_date": "Date synchro", "agent": "Agent", "locality": "Localite"},
        status="PENDING",
    )
    db_session.add(dashboard_import)
    db_session.commit()

    result = execute_dashboard_import(db_session, dashboard_import.id)

    assert result.total_rows == 5
    assert result.imported_rows == 3  # lignes 1,2,3 valides (la 3e est un doublon mais reste valide)
    assert result.rejected_rows == 2
    assert result.duplicate_rows == 1

    rows = db_session.query(DashboardImportRow).filter(
        DashboardImportRow.dashboard_import_id == dashboard_import.id
    ).all()
    assert any(r.is_duplicate for r in rows)
    assert any(not r.is_valid and "ID du groupe manquant" in r.validation_errors for r in rows)


def test_execute_without_mapping_raises(db_session):
    dashboard_import = DashboardImport(
        original_filename="dashboard.xlsx", storage_path="dashboard_imports/x.xlsx", column_mapping={}, status="PENDING"
    )
    db_session.add(dashboard_import)
    db_session.commit()

    with pytest.raises(DashboardImportError):
        execute_dashboard_import(db_session, dashboard_import.id)
