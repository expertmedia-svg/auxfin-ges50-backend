from pathlib import Path
import cv2
import pytest
from app.services.vision.pfnl_status import detect_pfnl_check
FIX = Path(__file__).parent / 'fixtures/status_icons'

@pytest.mark.parametrize('scale,padding', [(1,0), (.75,0), (2,0), (1,90)])
def test_real_check_resizing_letterboxing(tmp_path, scale, padding):
    im = cv2.imread(str(FIX / 'pfnlcoach_upload_confirmed_green.jpg'))
    # Cover the English operation labels: no translated text is required.
    im[102:125,365:605] = im[100,600]
    im = cv2.resize(im, None, fx=scale, fy=scale)
    im = cv2.copyMakeBorder(im,padding,padding,padding,padding,cv2.BORDER_CONSTANT,value=(0,0,0))
    path = tmp_path / 'frame.png'; cv2.imwrite(str(path),im)
    assert detect_pfnl_check(str(path))

def test_unchecked_real_panel():
    assert not detect_pfnl_check(str(FIX / 'pfnlcoach_start_before_upload.jpg'))

def test_green_disk_without_tick(tmp_path):
    im = cv2.imread(str(FIX / 'pfnlcoach_upload_confirmed_green.jpg'))
    cv2.circle(im,(342,106),10,(35,75,35),-1)
    path = tmp_path / 'disk.png'; cv2.imwrite(str(path),im)
    assert not detect_pfnl_check(str(path))


@pytest.mark.parametrize('text', ['', 'Télécharger les données Synchroniser Complété', 'Upload Data Completed'])
def test_pipeline_does_not_require_translated_success_text(monkeypatch, text):
    from app.models.enums import SyncStatus
    from app.services.vision import extraction_pipeline as pipeline
    from app.services.vision.ocr_engine import OcrEngineResult
    monkeypatch.setattr(pipeline, 'run_ocr_on_image_path',
                        lambda _: [OcrEngineResult('test', 'original', text, .9)])
    result = pipeline.extract_from_image(str(FIX / 'pfnlcoach_upload_confirmed_green.jpg'),
                                         [], [], application_code='pfnlcoach')
    assert result.sync_status == SyncStatus.SUCCESS


@pytest.mark.parametrize('name', ['financecoach_sync_confirmed_green.jpg',
                                 'yebcoach_sync_confirmed_green.jpg'])
def test_other_application_badges_do_not_confirm_pfnl(name):
    assert not detect_pfnl_check(str(FIX / name))
