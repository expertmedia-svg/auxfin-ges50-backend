from pathlib import Path
import cv2
import pytest
from app.models.enums import SyncStatus
from app.services.vision import extraction_pipeline as p
from app.services.vision.ocr_engine import OcrEngineResult

@pytest.mark.parametrize("name,app", [("pfnl_large","pfnlcoach"),("pfnl_small","pfnlcoach"),("water","watercoach"),("agri","agricoach")])
def test_reported_frames(monkeypatch,name,app):
    monkeypatch.setattr(p,"run_ocr_on_image_path",lambda _: [OcrEngineResult("test","original","",.9)])
    frame = Path(__file__).parent / "fixtures/portrait_coaches" / (name+".jpg")
    assert p.extract_from_image(str(frame),[],[],application_code=app).sync_status == SyncStatus.SUCCESS

def test_portrait_without_checks_is_not_confirmed(monkeypatch,tmp_path):
    frame = Path(__file__).parent / "fixtures/portrait_coaches/pfnl_large.jpg"
    image = cv2.imread(str(frame))
    # Remove the operation checks and badges while keeping the actual page.
    image[650:1100,125:185] = 255
    image[650:1100,1000:1080] = 255
    target = str(tmp_path / "empty.jpg")
    cv2.imwrite(target,image)
    monkeypatch.setattr(p,"run_ocr_on_image_path",lambda _: [OcrEngineResult("test","original","",.9)])
    assert p.extract_from_image(target,[],[],application_code="pfnlcoach").sync_status == SyncStatus.UNCONFIRMED
