"""FinanceCoach: locate the operation circles before looking for the badge."""
import cv2
import numpy as np
from app.services.vision.preprocessing import load_image_corrected


def detect_financecoach_status(path):
    """None outside the known menu; otherwise the visual confirmation state.

    Relative geometry tolerates letterboxing and different landscape sizes.
    The caller must first identify FinanceCoach.
    """
    return _detect_image(load_image_corrected(path))


def _detect_image(image):
    active = np.max(image, axis=2) > 18
    ys = np.where(active.mean(axis=1) > .3)[0]
    xs = np.where(active.mean(axis=0) > .3)[0]
    if not len(xs) or not len(ys):
        return None
    image = image[ys[0]:ys[-1]+1, xs[0]:xs[-1]+1]
    image = cv2.resize(image, (640, round(image.shape[0]*640/image.shape[1])))
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([85, 80, 65]), np.array([120, 255, 255]))
    kernel = max(3, round(w * .007))
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, np.ones((kernel, kernel), np.uint8))
    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    circles = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if (x > .45*w and .015*w < cw < .065*w and .75 < cw/max(ch, 1) < 1.3
                and cv2.contourArea(contour) > .55*cw*ch):
            circles.append((x+cw/2, y+ch/2, (cw+ch)/2))
    circles.sort(key=lambda c: c[1])
    for first in circles:
        x, y, diameter = first
        below = [c for c in circles if abs(c[0]-x) < diameter*.35
                 and .7 < c[2]/diameter < 1.3 and c[1] > y+diameter]
        if not below:
            continue
        second = below[0]
        gap = second[1]-y
        # Anchor on the first two operations. The third circle can touch the
        # blue background illustration and cannot reliably form a contour.
        data_menu = 4.5 < gap/diameter < 7
        if not (1.2 < gap/diameter < 3 or data_menu):
            continue
        # A checked operation box itself now suffices, even without a badge.
        for cx, cy, size in [first, *below]:
            inside = hsv[max(0, round(cy-size*.22)):round(cy+size*.22),
                         max(0, round(cx-size*.22)):round(cx+size*.22)]
            ink = cv2.inRange(inside, np.array([85, 80, 65]), np.array([120, 255, 255]))
            if _tick_shape(ink):
                return True
        crop = hsv[max(0, int(y)):min(h, int(second[1])),
                   max(0, int(x+diameter)):min(w, int(x+8*diameter))]
        if not crop.size:
            continue
        green = cv2.inRange(crop, np.array([35, 40, 40]), np.array([85, 255, 255]))
        badges, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for badge in badges:
            bx, by, bw, bh = cv2.boundingRect(badge)
            if (.2 < bw/diameter < .8 and .65 < bw/max(bh, 1) < 1.5
                    and cv2.contourArea(badge) > .4*bw*bh):
                found.append((bx+bw/2, by+bh/2))
        if not data_menu:
            return bool(found)
        # Operator rule: one completed suboperation is sufficient.
        return bool(found)
    return None



def _tick_shape(mask):
    if not mask.size:
        return False
    count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if w < mask.shape[1]*.45 or h < mask.shape[0]*.25 or not .06 < area/mask.size < .65:
            continue
        yy, xx = np.where(components == i)
        left = yy[xx < x+w*.2]
        middle = yy[(xx >= x+w*.2) & (xx < x+w*.5)]
        right = yy[xx >= x+w*.75]
        if len(left) and len(middle) and len(right) and middle.mean() > left.mean() and middle.mean() > right.mean()+h*.1:
            return True
    return False

def scan_finance_video(video_path, output_dir, evidence_id):
    """Bounded visual scan; save state changes only, without running extra OCR."""
    from pathlib import Path
    capture = cv2.VideoCapture(video_path)
    results = []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or count <= 0:
            return results
        duration = count / fps
        step = max(.25, duration / 1200)
        previous = None
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(min(1200, int(duration / step) + 1)):
            timestamp = index * step
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, image = capture.read()
            if not ok:
                break
            state = _detect_image(image)
            if state is None or state == previous:
                continue
            path = str(directory / f"{evidence_id}_visual_{timestamp:.3f}.png")
            if cv2.imwrite(path, image):
                results.append((timestamp, path))
                previous = state
        return results
    finally:
        capture.release()
