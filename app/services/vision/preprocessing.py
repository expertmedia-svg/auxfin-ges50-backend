"""Pretraitement d'image avant OCR (etapes 1 a 7 du pipeline, section 8 du cahier
des charges) : orientation EXIF, espace de couleur, contraste, bruit, redimensionnement,
puis generation de plusieurs variantes a tester par l'OCR.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class PreprocessedVariant:
    name: str
    image: np.ndarray  # BGR uint8, pret pour OCR


def load_image_corrected(path: str) -> np.ndarray:
    """Charge une image, corrige l'orientation EXIF, retourne un tableau BGR OpenCV."""
    with Image.open(path) as pil_image:
        pil_image = ImageOps.exif_transpose(pil_image)
        pil_image = pil_image.convert("RGB")
        rgb = np.array(pil_image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _smart_resize(image: np.ndarray, target_min_dim: int = 800, max_dim: int = 2400) -> np.ndarray:
    h, w = image.shape[:2]
    min_dim = min(h, w)
    if min_dim < target_min_dim:
        scale = target_min_dim / min_dim
    elif max(h, w) > max_dim:
        scale = max_dim / max(h, w)
    else:
        return image
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)


def _clahe_contrast(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def generate_variants(image: np.ndarray) -> list[PreprocessedVariant]:
    """Genere plusieurs variantes pretraitees ; l'OCR est ensuite tente sur chacune
    et le meilleur resultat (confiance la plus haute) est retenu."""
    resized = _smart_resize(image)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    contrast = _clahe_contrast(gray)
    denoised = _denoise(contrast)
    _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )

    def to_bgr(gray_img: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(gray_img, cv2.COLOR_GRAY2BGR)

    return [
        PreprocessedVariant("original_resized", resized),
        PreprocessedVariant("contrast_denoised", to_bgr(denoised)),
        PreprocessedVariant("otsu_threshold", to_bgr(otsu)),
        PreprocessedVariant("adaptive_threshold", to_bgr(adaptive)),
    ]
