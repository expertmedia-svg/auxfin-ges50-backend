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
    assert "Data" in result.sync_status_evidence_text


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


@pytest.mark.parametrize("checked", [True, False])
@pytest.mark.parametrize("text", ["", "Yeb Data", "Upload Synchroniser Données"])
def test_yeb_data_first_checkbox_without_meta(tmp_path, checked, text):
    import cv2
    import numpy as np
    from app.services.vision.yebcoach_status import detect_yebcoach_data_checked
    image = np.full((400, 640, 3), 255, dtype=np.uint8)
    cv2.circle(image, (400, 110), 14, (65, 65, 185), -1)
    cv2.rectangle(image, (394, 104), (406, 116), (255, 255, 255), -1 if checked else 1)
    if checked:
        cv2.line(image, (396, 110), (399, 113), (65, 65, 185), 2)
        cv2.line(image, (399, 113), (404, 106), (65, 65, 185), 2)
    path = str(tmp_path / "data.png")
    cv2.imwrite(path, image)
    assert detect_yebcoach_data_checked(path, text) is checked


@pytest.mark.parametrize("checked", [True, False])
def test_yeb_three_row_menu_uses_second_checkbox_without_ocr(tmp_path, checked):
    import cv2
    from app.services.vision.yebcoach_status import detect_yebcoach_data_checked
    image = cv2.imread(str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"))
    # The real fixture has Upload checked but Data empty.
    if checked:
        cv2.rectangle(image, (394, 161), (406, 173), (255, 255, 255), -1)
        cv2.line(image, (396, 167), (399, 170), (65, 65, 185), 2)
        cv2.line(image, (399, 170), (404, 163), (65, 65, 185), 2)
    path = str(tmp_path / "second.png")
    cv2.imwrite(path, image)
    assert detect_yebcoach_data_checked(path, "") is checked


@pytest.mark.parametrize("app,filename,expected", [
    ("financecoach", "financecoach_sync_confirmed_green.jpg", SyncStatus.SUCCESS),
    ("financecoach", "financecoach_start_before_sync.jpg", SyncStatus.UNCONFIRMED),
    ("financecoach", "yebcoach_sync_confirmed_green.jpg", SyncStatus.UNCONFIRMED),
    ("yebcoach", "yebcoach_sync_confirmed_green.jpg", SyncStatus.UNCONFIRMED),
    ("yebcoach", "yebcoach_final_menu_with_red_button.jpg", SyncStatus.UNCONFIRMED),
])
@pytest.mark.parametrize("text", ["", "Complété", "Completed"])
def test_visual_rules_without_labels_or_configured_zone(monkeypatch, app, filename, expected, text):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path",
                        lambda _: [OcrEngineResult("test", "original", text, .9)])
    result = pipeline.extract_from_image(str(FIXTURES_DIR / filename),
                                        ["Complété", "Completed"], [], application_code=app)
    assert result.sync_status == expected
