"""Règle AgriCoach : upload_data ET download_data cochés sur le même écran.

Calibrée sur la vidéo du 14/09/2026 fournie par l'opérateur (640 x 400).
Les libellés OCR et la forme blanche des coches sont requis en plus du vert.
"""
import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.services.vision.preprocessing import load_image_corrected


@dataclass
class AgriCoachStatus:
    confirmed: bool
    upload_checked: bool
    download_checked: bool
    panel_visible: bool = False


def _checked(image: np.ndarray, x: float, y: float) -> bool:
    height, width = image.shape[:2]
    # Zone étroite autour de la case, sans les bordures de la ligne.
    crop = image[round(y * height):round((y + .055) * height),
                 round(x * width):round((x + .038) * width)]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 65, 65]), np.array([85, 255, 255]))
    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if not .65 <= bw / max(bh, 1) <= 1.5 or bw < crop.shape[1] * .45 or bh < crop.shape[0] * .45:
            continue
        if cv2.contourArea(contour) < .45 * bw * bh:
            continue
        inside = hsv[by + 1:by + bh - 1, bx + 1:bx + bw - 1]
        white = cv2.inRange(inside, np.array([0, 0, 175]), np.array([179, 100, 255]))
        count, components, stats, _ = cv2.connectedComponentsWithStats(white)
        for index in range(1, count):
            sx, sy, sw, sh, area = stats[index]
            if sw >= .45 * bw and sh >= .25 * bh and .035 * bw * bh <= area <= .4 * bw * bh:
                yy, xx = np.where(components == index)
                left = yy[xx < sx + sw * .2]
                middle = yy[(xx >= sx + sw * .2) & (xx < sx + sw * .45)]
                right = yy[xx >= sx + sw * .75]
                if (len(left) and len(middle) and len(right)
                        and middle.mean() > left.mean()
                        and middle.mean() > right.mean() + .1 * bh):
                    return True
    return False


def detect_agricoach_status(path: str, text: str) -> AgriCoachStatus:
    labels = re.sub(r"[^a-z]", "", text.lower())
    if "uploaddata" not in labels or "downloaddata" not in labels:
        return AgriCoachStatus(False, False, False)
    image = load_image_corrected(path)
    height, width = image.shape[:2]
    if not 1.52 <= width / height <= 1.68:
        return AgriCoachStatus(False, False, False)
    upload = _checked(image, .61, .115)
    download = _checked(image, .61, .2175)
    return AgriCoachStatus(upload and download, upload, download, True)
