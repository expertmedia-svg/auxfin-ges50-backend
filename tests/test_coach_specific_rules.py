import pytest

from app.models.enums import SyncStatus
from app.services.vision import extraction_pipeline as pipeline
from app.services.vision.ocr_engine import OcrEngineResult
from tests.test_status_icon import FINANCECOACH_ICON_ZONE, FIXTURES_DIR, PFNLCOACH_ICON_ZONE, YEBCOACH_ICON_ZONE


@pytest.mark.parametrize("filename,expected", [
    ("pfnlcoach_upload_confirmed_green.jpg", SyncStatus.SUCCESS),
    ("pfnlcoach_start_before_upload.jpg", SyncStatus.UNCONFIRMED),
])
def test_pfnl_upload_label_needs_green_first_checkbox(monkeypatch, filename, expected):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path", lambda _: [OcrEngineResult("test", "original", "Upload Data", .9)])
    result = pipeline.extract_from_image(str(FIXTURES_DIR / filename), ["upload data"], [],
                                          application_code="pfnlcoach", status_icon_zone=PFNLCOACH_ICON_ZONE)
    assert result.sync_status == expected


def test_yeb_old_upload_badge_does_not_confirm_data_and_meta(monkeypatch):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path",
                        lambda _: [OcrEngineResult("test", "original", "Upload Synchroniser Données Méta success", .9)])
    result = pipeline.extract_from_image(str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"), ["success"], [],
                                          application_code="yebcoach", status_icon_zone=YEBCOACH_ICON_ZONE)
    assert result.sync_status == SyncStatus.UNCONFIRMED
    assert "Data et Meta" in result.sync_status_evidence_text


@pytest.mark.parametrize("filename,expected", [
    ("financecoach_sync_confirmed_green.jpg", SyncStatus.SUCCESS),
    ("financecoach_start_before_sync.jpg", SyncStatus.UNCONFIRMED),
])
def test_finance_existing_badge_rule_preserved(monkeypatch, filename, expected):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path",
                        lambda _: [OcrEngineResult("test", "original", "FinanceCoach Télécharger Synchroniser", .9)])
    result = pipeline.extract_from_image(str(FIXTURES_DIR / filename), [], [],
                                          application_code="financecoach", status_icon_zone=FINANCECOACH_ICON_ZONE)
    assert result.sync_status == expected
