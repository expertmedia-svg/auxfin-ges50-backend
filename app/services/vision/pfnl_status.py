"""PFNL sync panel: visual check, independent of translated labels."""
import cv2
import numpy as np
from app.services.vision.preprocessing import load_image_corrected


def detect_pfnl_check(path: str, *, any_operation: bool = False) -> bool:
    """Recognize the first checked disk in the known landscape PFNL panel.

    The caller must identify PFNLCoach first. Text is not needed; an unknown
    layout or an indistinct check is left unconfirmed.
    """
    return detect_check_image(load_image_corrected(path), any_operation=any_operation)


def detect_check_image(image, *, any_operation=False):
    # Remove black letterboxing, retaining the complete visible application.
    active = np.max(image, axis=2) > 18
    ys = np.where(active.mean(axis=1) > .3)[0]
    xs = np.where(active.mean(axis=0) > .3)[0]
    if not len(xs) or not len(ys):
        return False
    image = image[ys[0]:ys[-1]+1, xs[0]:xs[-1]+1]
    image = cv2.resize(image, (960, round(image.shape[0] * 960 / image.shape[1])))
    h, w = image.shape[:2]
    if not 1.3 < w/h < 2.1:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([30, 45, 25]), np.array([90, 255, 255]))
    # First operation only. The logo and subsequent operations are excluded.
    top, bottom, roi_left, roi_right = (.10, .85, .47, .95) if any_operation else (.18, .36, .47, .58)
    roi = mask[int(top*h):int(bottom*h), int(roi_left*w):int(roi_right*w)]
    cleaned = cv2.morphologyEx(roi, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if not .7 < cw/max(ch,1) < 1.4 or not .025*h < ch < .08*h:
            continue
        if cv2.contourArea(contour) < .5*cw*ch:
            continue
        x += int(roi_left*w); y += int(top*h)
        crop = hsv[y:y+ch, x:x+cw]
        # White check inside a filled green disk, not a green disk alone.
        white = ((crop[:,:,1] < 105) & (crop[:,:,2] > max(50, np.median(crop[:,:,2])*1.15))).astype('uint8')
        white[:2] = 0; white[-2:] = 0; white[:,:2] = 0; white[:,-2:] = 0
        count, components, stats, _ = cv2.connectedComponentsWithStats(white)
        for i in range(1, count):
            sx, sy, sw, sh, area = stats[i]
            if sw < .35*cw or sh < .2*ch or not .02*cw*ch < area < .4*cw*ch:
                continue
            yy, xx = np.where(components == i)
            left = yy[xx < sx+sw*.15]; middle = yy[(xx >= sx+sw*.15) & (xx < sx+sw*.5)]; right = yy[xx >= sx+sw*.75]
            if len(left) and len(middle) and len(right) and middle.mean() > left.mean() and middle.mean() > right.mean()+.08*ch:
                return True
    return False
