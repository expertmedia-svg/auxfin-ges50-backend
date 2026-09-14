from pathlib import Path

import pytest

from app.models.enums import SyncStatus
from app.services.video.frame_extractor import VideoMetadata
from app.services.vision import extraction_pipeline as pipeline
from app.services.vision.agricoach_status import detect_agricoach_status
from app.services.vision.ocr_engine import OcrEngineResult

FIXTURES = Path(__file__).parent / "fixtures" / "agricoach_checks"
LABELS = "AgriCoach upload_data download_data download_media"


@pytest.mark.parametrize("filename,expected", [("both_checked.jpg", True), ("upload_only.jpg", False), ("home.jpg", False)])
def test_real_frames_require_both_checks(filename, expected):
    assert detect_agricoach_status(str(FIXTURES / filename), LABELS).confirmed is expected


def test_labels_required_even_with_green_checks():
    assert not detect_agricoach_status(str(FIXTURES / "both_checked.jpg"), "Guide Meteo").confirmed


def test_agricoach_confirmation_survives_return_home_and_does_not_apply_to_other_apps(monkeypatch):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path", lambda _: [OcrEngineResult("test", "original", LABELS, .9)])
    outcome = pipeline.extract_from_image(str(FIXTURES / "both_checked.jpg"), [], [])
    outcome.video_metadata = VideoMetadata(47.5, 640, 400)
    outcome.frame_debug = [
        pipeline.FrameOcrDebug("middle", 12, str(FIXTURES / "both_checked.jpg"), LABELS, .9),
        pipeline.FrameOcrDebug("end", 2, str(FIXTURES / "home.jpg"), "AgriCoach Guide Meteo", .9),
    ]
    pipeline.evaluate_sync_frames(outcome, [], [], application_code="agricoach")
    assert outcome.sync_status == SyncStatus.SUCCESS
    for app in [None, "financecoach", "pfnlcoach", "yebcoach"]:
        pipeline.evaluate_sync_frames(outcome, [], [], application_code=app)
        assert outcome.sync_status == SyncStatus.UNCONFIRMED


def test_error_after_checks_remains_failure(monkeypatch):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path", lambda _: [OcrEngineResult("test", "original", LABELS, .9)])
    outcome = pipeline.extract_from_image(str(FIXTURES / "both_checked.jpg"), [], [])
    outcome.video_metadata = VideoMetadata(47.5, 640, 400)
    outcome.frame_debug = [
        pipeline.FrameOcrDebug("middle", 12, str(FIXTURES / "both_checked.jpg"), LABELS, .9),
        pipeline.FrameOcrDebug("end", 2, str(FIXTURES / "home.jpg"), "failed", .9),
    ]
    pipeline.evaluate_sync_frames(outcome, [], ["failed"], application_code="agricoach")
    assert outcome.sync_status == SyncStatus.FAILED


def test_success_keyword_without_both_checks_does_not_confirm_agricoach(monkeypatch):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path",
                        lambda _: [OcrEngineResult("test", "original", LABELS + " success", .9)])
    outcome = pipeline.extract_from_image(str(FIXTURES / "upload_only.jpg"), ["success"], [], application_code="agricoach")
    assert outcome.sync_status == SyncStatus.UNCONFIRMED
