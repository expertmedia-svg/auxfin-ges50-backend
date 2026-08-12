"""Detection du statut de synchronisation via la couleur d'une icone d'etat
(ex: cercle qui passe de gris/flou a une coche verte), pour les applications
ou la confirmation n'est jamais exprimee par un mot-cle textuel lisible par
l'OCR.

Bug/limite reelle trouvee en Phase C : sur YEBCoach, le bouton "Synchroniser"
est suivi d'une icone circulaire qui devient verte une fois la synchronisation
terminee — mais aucun texte de confirmation n'apparait jamais a l'ecran.
`sync_status.py` (mots-cles textuels) ne peut structurellement pas detecter
ce cas. Ce module est un signal complementaire, pas un remplacement : voir
son utilisation dans extraction_pipeline.py (n'est utilise que pour confirmer
un succes quand aucun mot-cle textuel n'a rien trouve — jamais pour
fabriquer un echec, la detection de rouge etant trop peu fiable sur
l'echantillon reel observe, cf. docs/CALIBRATION_APPLICATIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.services.vision.preprocessing import load_image_corrected

# Plages HSV (OpenCV : H 0-179, S/V 0-255).
_GREEN_LOWER = np.array([35, 40, 40])
_GREEN_UPPER = np.array([85, 255, 255])

# Seuil minimal de pixels verts dans la zone pour conclure a une icone verte.
# Calibre sur deux applications reelles : YEBCoach (ratio 0.114) et
# PFNLCoach (ratio 0.065-0.071, icone plus petite relativement a sa zone) ;
# 0.0 sur toutes les frames sans confirmation observees dans les deux cas.
GREEN_CONFIRMATION_THRESHOLD = 0.05


@dataclass
class IconColorResult:
    is_green: bool
    green_ratio: float


def _crop_relative_zone(image: np.ndarray, zone: dict) -> np.ndarray | None:
    """zone : {"x", "y", "w", "h"} en fractions (0-1) de la largeur/hauteur
    totale — meme convention que les autres zones de
    ApplicationProfile.screen_zones (ex. "id_date_header")."""
    h, w = image.shape[:2]
    x = int(zone.get("x", 0) * w)
    y = int(zone.get("y", 0) * h)
    zw = int(zone.get("w", 0) * w)
    zh = int(zone.get("h", 0) * h)
    if zw <= 0 or zh <= 0:
        return None
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    zw = max(1, min(zw, w - x))
    zh = max(1, min(zh, h - y))
    return image[y : y + zh, x : x + zw]


def detect_status_icon_color(image_path: str, zone: dict) -> IconColorResult:
    image = load_image_corrected(image_path)
    crop = _crop_relative_zone(image, zone)
    if crop is None or crop.size == 0:
        return IconColorResult(is_green=False, green_ratio=0.0)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    total_pixels = hsv.shape[0] * hsv.shape[1]
    if total_pixels == 0:
        return IconColorResult(is_green=False, green_ratio=0.0)

    green_mask = cv2.inRange(hsv, _GREEN_LOWER, _GREEN_UPPER)
    green_ratio = cv2.countNonZero(green_mask) / total_pixels
    return IconColorResult(is_green=green_ratio >= GREEN_CONFIRMATION_THRESHOLD, green_ratio=round(green_ratio, 4))
