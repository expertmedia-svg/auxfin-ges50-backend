"""YEBCoach : case Data cochée, sans exigence sur Meta (règle opérateur)."""
import re
import unicodedata

import cv2
import numpy as np

from app.services.vision.preprocessing import load_image_corrected


def detect_yebcoach_data_checked(path, text):
    labels = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    if not re.search(r"\b(data|donnees)\b", labels):
        return False
    image = load_image_corrected(path)
    height, width = image.shape[:2]
    if not 1.52 <= width / height <= 1.68:
        return False
    # Deux menus connus : Data première ligne, ou Données après Upload.
    center_y = .418 if re.search(r"\bupload\b", labels) else .275
    surround = image[round((center_y - .032) * height):round((center_y + .032) * height),
                     round(.606 * width):round(.645 * width)]
    ring = cv2.cvtColor(surround, cv2.COLOR_BGR2HSV)
    red = ((ring[:, :, 0] < 12) | (ring[:, :, 0] > 165)) & (ring[:, :, 1] > 90)
    if float(np.count_nonzero(red)) / red.size < .25:
        return False
    crop = image[round((center_y - .012) * height):round((center_y + .012) * height),
                 round(.618 * width):round(.633 * width)]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([179, 65, 255]))
    # La case cochée a un fond blanc ; la case vide garde son centre rouge.
    ratio = float(np.count_nonzero(white)) / white.size
    return .30 < ratio < .95

