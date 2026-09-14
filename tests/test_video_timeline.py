from datetime import date

import pytest

from app.models.enums import SyncStatus
from app.services.video import frame_extractor as video
from app.services.vision import extraction_pipeline as pipeline
from app.services.vision.ocr_engine import OcrEngineResult


@pytest.mark.parametrize("final_text,expected", [("Menu", SyncStatus.SUCCESS), ("failed", SyncStatus.FAILED)])
def test_recovers_id_date_and_sync_in_middle_without_ignoring_final_error(monkeypatch, final_text, expected):
    metadata = video.VideoMetadata(60, 640, 400)
    initial = [video.ExtractedFrame("start", 0, "start"), video.ExtractedFrame("end", 1, "end")]
    middle = [video.ExtractedFrame("middle", 30, "middle")]
    monkeypatch.setattr(pipeline, "extract_start_end_frames", lambda *args: (metadata, initial))
    monkeypatch.setattr(pipeline, "extract_timeline_frames", lambda *args: middle)
    texts = {"start": "AgriCoach", "end": final_text,
             "middle": "gr13.kar-vigue-deguele 14/09/2026 synchronisation terminee"}
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path",
                        lambda path: [OcrEngineResult("test", "original", texts[path], 0.95)])
    outcome = pipeline.extract_from_video("unused", "unused", "test", ["synchronisation terminee"],
                                          ["failed"], context_date=date(2026, 9, 14))
    assert outcome.normalized_group_id == "gr13.kar-vigue-deguele"
    assert outcome.normalized_date == "2026-09-14"
    assert outcome.sync_status == expected
    assert outcome.requires_manual_review == (expected != SyncStatus.SUCCESS)
    assert middle[0] in outcome.extracted_frames


def test_timeline_sampling_bounded_and_avoids_existing_frames(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(video, "_extract_single_frame", lambda source, timestamp, path: calls.append(timestamp) or True)
    frames = video.extract_timeline_frames("test", str(tmp_path), "test", video.VideoMetadata(34, 640, 400),
                                          [video.ExtractedFrame("start", 2, "start")])
    assert len(frames) == 15
    assert 2 not in calls
    assert 16 in calls
    assert all(0 < timestamp < 34 for timestamp in calls)
