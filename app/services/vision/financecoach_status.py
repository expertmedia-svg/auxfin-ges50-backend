"""Language-independent FinanceCoach badge on the calibrated landscape menu."""
import cv2
import numpy as np

from app.services.vision.preprocessing import load_image_corrected
from app.services.vision.status_icon import detect_status_icon_color


def detect_financecoach_status(path):
    """Return None outside the known menu, otherwise its visual sync state."""
    image = load_image_corrected(path)
    h, w = image.shape[:2]
    if not 1.52 <= w / h <= 1.68:
        return None
    # Both blue operation circles anchor the menu; blue alone is not success.
    for cy in (.25, .385):
        crop = image[round((cy-.035)*h):round((cy+.035)*h),
                     round(.59*w):round(.645*w)]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, np.array([85, 80, 65]), np.array([120, 255, 255]))
        if cv2.countNonZero(blue) / blue.size < .15:
            return None
    return detect_status_icon_color(path, {"x": .83, "y": .27, "w": .07, "h": .11}).is_green
