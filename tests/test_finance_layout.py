from pathlib import Path
import cv2
import pytest
from app.services.vision.financecoach_status import detect_financecoach_status

FIX = Path(__file__).parent / "fixtures/status_icons"

@pytest.mark.parametrize("size,padding", [((640,360),0), ((960,540),80), ((480,300),40), ((1280,800),0)])
@pytest.mark.parametrize("confirmed", [True, False])
def test_layout_resize_and_letterboxing(tmp_path, size, padding, confirmed):
    name = "financecoach_sync_confirmed_green.jpg" if confirmed else "financecoach_start_before_sync.jpg"
    image = cv2.resize(cv2.imread(str(FIX/name)), size)
    image = cv2.copyMakeBorder(image,padding,padding,padding,padding,cv2.BORDER_CONSTANT,value=0)
    path = str(tmp_path/"frame.png")
    cv2.imwrite(path,image)
    assert (detect_financecoach_status(path) is True) == confirmed


@pytest.mark.parametrize("name,expected", [("t24.jpg", False), ("t27.jpg", True),
    ("second12.jpg", True), ("second1825.jpg", True), ("second185.jpg", None)])
def test_reported_real_video_frames(name, expected):
    path = Path(__file__).parent / "fixtures/finance_regression" / name
    assert detect_financecoach_status(str(path)) is expected


def test_brief_success_before_android_menu_is_retained(tmp_path):
    from app.services.vision.financecoach_status import scan_finance_video
    root = Path(__file__).parent / "fixtures/finance_regression"
    video = str(tmp_path / "short.avi")
    writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 4, (640,400))
    for name in ["t24.jpg", "t24.jpg", "t27.jpg", "second185.jpg"]:
        writer.write(cv2.imread(str(root/name)))
    writer.release()
    frames = scan_finance_video(video, str(tmp_path), "test")
    assert [detect_financecoach_status(path) for _, path in frames] == [False, True]
