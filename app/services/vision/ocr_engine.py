"""Moteur OCR modulaire : EasyOCR en moteur principal, Tesseract en moteur
secondaire (section 8). Teste plusieurs variantes pretraitees et conserve le
meilleur resultat (texte brut, confiance, boites englobantes).
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field

import numpy as np

from app.services.vision.preprocessing import generate_variants, load_image_corrected

logger = logging.getLogger(__name__)


@dataclass
class OcrEngineResult:
    engine: str
    preprocessing_variant: str
    raw_text: str
    confidence: float  # 0..1
    boxes: list[dict] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def _get_easyocr_reader():
    import easyocr

    return easyocr.Reader(["fr", "en"], gpu=False, verbose=False)


def _run_easyocr(image: np.ndarray, variant_name: str) -> OcrEngineResult | None:
    try:
        reader = _get_easyocr_reader()
        detections = reader.readtext(image)
    except Exception:
        logger.exception("EasyOCR a echoue sur la variante %s", variant_name)
        return None

    if not detections:
        return OcrEngineResult(
            engine="easyocr", preprocessing_variant=variant_name, raw_text="", confidence=0.0, boxes=[]
        )

    texts = [d[1] for d in detections]
    confidences = [float(d[2]) for d in detections]
    boxes = [
        {"text": d[1], "confidence": float(d[2]), "polygon": [[float(x), float(y)] for x, y in d[0]]}
        for d in detections
    ]
    return OcrEngineResult(
        engine="easyocr",
        preprocessing_variant=variant_name,
        raw_text="\n".join(texts),
        confidence=sum(confidences) / len(confidences),
        boxes=boxes,
    )


def _run_tesseract(image: np.ndarray, variant_name: str) -> OcrEngineResult | None:
    try:
        import cv2
        import pytesseract

        from app.core.config import get_settings

        settings = get_settings()
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(
            rgb, lang="fra+eng", output_type=pytesseract.Output.DICT
        )
    except Exception:
        logger.exception("Tesseract a echoue sur la variante %s", variant_name)
        return None

    words: list[str] = []
    confidences: list[float] = []
    boxes: list[dict] = []
    for i, word in enumerate(data.get("text", [])):
        if not word.strip():
            continue
        conf = float(data["conf"][i]) if data["conf"][i] not in ("-1", -1) else 0.0
        words.append(word)
        confidences.append(max(conf, 0.0))
        boxes.append(
            {
                "text": word,
                "confidence": conf / 100,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
            }
        )

    avg_conf = (sum(confidences) / len(confidences) / 100) if confidences else 0.0
    return OcrEngineResult(
        engine="tesseract",
        preprocessing_variant=variant_name,
        raw_text=" ".join(words),
        confidence=avg_conf,
        boxes=boxes,
    )


def run_ocr_on_image_path(image_path: str) -> list[OcrEngineResult]:
    """Execute l'OCR (EasyOCR + Tesseract) sur toutes les variantes pretraitees
    d'une image et retourne tous les resultats obtenus, tries par confiance
    decroissante. L'appelant choisit ensuite le meilleur resultat exploitable."""
    image = load_image_corrected(image_path)
    variants = generate_variants(image)

    results: list[OcrEngineResult] = []
    for variant in variants:
        easy_result = _run_easyocr(variant.image, variant.name)
        if easy_result is not None:
            results.append(easy_result)
        tess_result = _run_tesseract(variant.image, variant.name)
        if tess_result is not None:
            results.append(tess_result)

    results.sort(key=lambda r: r.confidence, reverse=True)
    return results


def best_result(results: list[OcrEngineResult]) -> OcrEngineResult | None:
    non_empty = [r for r in results if r.raw_text.strip()]
    return non_empty[0] if non_empty else (results[0] if results else None)


def combined_text(results: list[OcrEngineResult], top_n: int = 3) -> str:
    """Concatene le texte des meilleurs resultats (toutes variantes/moteurs
    confondus) pour maximiser les chances de trouver l'ID/la date/le statut,
    meme s'ils ne sont pas tous dans le meilleur resultat unique."""
    seen: set[str] = set()
    chunks: list[str] = []
    for r in results[:top_n]:
        if r.raw_text and r.raw_text not in seen:
            seen.add(r.raw_text)
            chunks.append(r.raw_text)
    return "\n".join(chunks)
