from pathlib import Path
from app.models.enums import SyncStatus
from app.services.vision import extraction_pipeline as p
from app.services.vision.ocr_engine import OcrEngineResult
from app.services.video.frame_extractor import VideoMetadata


def test_android_bluetooth_failure_does_not_override_visual_success(monkeypatch):
    path = str(Path(__file__).parent / "fixtures/status_icons/financecoach_sync_confirmed_green.jpg")
    monkeypatch.setattr(p, "run_ocr_on_image_path", lambda _: [OcrEngineResult("test", "original", "", .9)])
    outcome = p.extract_from_image(path, [], [], application_code="financecoach")
    outcome.video_metadata = VideoMetadata(10,640,400)
    outcome.frame_debug = [p.FrameOcrDebug("middle",6,path,"",.9),
        p.FrameOcrDebug("end",1,path,"Enregistrement de l'écran Bluetooth échec du transfert Gérer notifications",.9)]
    p.evaluate_sync_frames(outcome, [], ["échec"], application_code="financecoach")
    assert outcome.sync_status == SyncStatus.SUCCESS
    outcome.frame_debug[-1].raw_text = "Synchronisation échec"
    p.evaluate_sync_frames(outcome, [], ["échec"], application_code="financecoach")
    assert outcome.sync_status == SyncStatus.FAILED
