from scripts.add_watercoach import add_watercoach
from scripts.seed_config import APPLICATION_PROFILES
from app.models.applications import Application, ApplicationProfile
from app.services.vision.application_detector import detect_application


def test_add_watercoach_preserves_existing_configuration(db_session):
    first = add_watercoach(db_session)
    profile = db_session.query(ApplicationProfile).filter_by(application_id=first).one()
    profile.logo_keywords = ["custom watercoach"]
    db_session.commit()
    assert add_watercoach(db_session) == first
    assert db_session.query(Application).filter_by(code="watercoach").count() == 1
    assert profile.logo_keywords == ["custom watercoach"]


def test_watercoach_detected_among_other_coaches():
    apps = [(p["code"],p["code"],p["name"],p["logo_keywords"]) for p in APPLICATION_PROFILES]
    for text in ["WATERCOACH", "Water Coach Synchroniser"]:
        assert detect_application(text, apps).application_code == "watercoach"


import cv2
import pytest
from pathlib import Path
from app.services.vision import extraction_pipeline as pipeline
from app.services.vision.ocr_engine import OcrEngineResult
from app.models.enums import SyncStatus


@pytest.mark.parametrize("mode", ["blue", "green_only", "no_check"])
def test_real_watercoach_visual_rule(monkeypatch, tmp_path, mode):
    root = Path(__file__).parent / "fixtures/watercoach"
    image = cv2.imread(str(root / ("green_badges.jpg" if mode == "green_only" else "blue_checks.jpg")))
    if mode == "green_only":
        image[100:173, 377:401] = 255
    if mode == "no_check":
        # Remove only the white ticks, retaining solid blue operation disks.
        for x,y in [(389,112),(389,158)]:
            colour = tuple(int(v) for v in image[y,x-4])
            cv2.circle(image,(x,y),9,colour,-1)
    path = str(tmp_path / "water.jpg")
    cv2.imwrite(path,image)
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path", lambda _: [OcrEngineResult("test", "original", "WaterCoach DYU", .9)])
    outcome = pipeline.extract_from_image(path, [], [], application_code="watercoach")
    assert outcome.sync_status == (SyncStatus.UNCONFIRMED if mode == "no_check" else SyncStatus.SUCCESS)
