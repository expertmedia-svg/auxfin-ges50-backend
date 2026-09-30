"""YEBCoach : case Data cochée, sans exigence sur Meta (règle opérateur)."""

import cv2
import numpy as np

from app.services.vision.preprocessing import load_image_corrected


def detect_yebcoach_data_state(path, *, any_operation=False):
    """True/False for a known Data panel, None for an unrelated screen."""
    image = load_image_corrected(path)
    if any_operation:
        # Android's black navigation strip shifts the checkbox horizontally.
        xs = np.where((np.max(image, axis=2) > 18).mean(axis=0) > .3)[0]
        if len(xs):
            image = image[:, xs[0]:xs[-1]+1]
    height, width = image.shape[:2]
    if not 1.52 <= width / height <= 1.68:
        return None
    if any_operation:
        # Known operation rows, including Upload before Data.
        for center in (.275, .418, .625):
            crop = image[round((center-.012)*height):round((center+.012)*height),
                         round(.618*width):round(.633*width)]
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            white = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([179, 65, 255]))
            ratio = float(np.count_nonzero(white)) / white.size
            ring = image[round((center-.032)*height):round((center+.032)*height),
                         round(.606*width):round(.645*width)]
            hsv_ring = cv2.cvtColor(ring, cv2.COLOR_BGR2HSV)
            red = ((hsv_ring[:,:,0] < 12) | (hsv_ring[:,:,0] > 165)) & (hsv_ring[:,:,1] > 90)
            if red.mean() > .25 and .30 < ratio < .95:
                return True
    # Deux menus connus : Data première ligne, ou Données après Upload.
    def red_disk(center):
        crop = image[round((center-.032)*height):round((center+.032)*height),
                     round(.606*width):round(.645*width)]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        red = ((hsv[:,:,0] < 12) | (hsv[:,:,0] > 165)) & (hsv[:,:,1] > 90)
        return float(np.count_nonzero(red)) / red.size > .25

    # Three-row menu: Upload, Data, Boutique. Never mistake Upload for Data.
    if red_disk(.418) and red_disk(.625):
        center_y = .418
    elif red_disk(.275) and not red_disk(.418):
        center_y = .275
    else:
        return None
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



def detect_yebcoach_data_checked(path, text=""):
    """Compatibility wrapper; translated OCR labels are not required."""
    return detect_yebcoach_data_state(path) is True
