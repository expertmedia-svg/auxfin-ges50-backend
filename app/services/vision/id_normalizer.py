"""Normalisation robuste des identifiants de groupe G50 lus par OCR.

Format cible : ``gr<numero>.<slug-en-minuscules-avec-tirets>`` (ex: ``gr1.loumbila-nonguestenga``).
Le texte source vient d'un OCR potentiellement bruite (majuscules, tirets/espaces
interchanges, confusions O/0, I/l/1, S/5, B/8, Z/2, unicode...).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

ID_PATTERN = re.compile(r"^gr(\d+)\.([a-z0-9\-]+)$")

# Confusions OCR frequentes, appliquees uniquement au segment numerique juste apres "gr"
# ou l'on sait qu'il ne peut s'agir que de chiffres.
_DIGIT_CONFUSIONS = {
    "o": "0", "O": "0",
    "i": "1", "I": "1", "l": "1", "L": "1",
    "s": "5", "S": "5",
    "b": "8", "B": "8",
    "z": "2", "Z": "2",
}

_DASH_CHARS = {"‐", "‑", "‒", "–", "—", "―", "_", " "}


@dataclass
class NormalizationResult:
    raw: str
    normalized: str | None
    is_valid_format: bool
    corrections: list[str] = field(default_factory=list)
    confidence: float = 0.0
    fuzzy_match: str | None = None
    fuzzy_score: float | None = None
    fuzzy_candidates: list[tuple[str, float]] = field(default_factory=list)
    requires_manual_review: bool = False


def _clean_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).strip()
    for dash in _DASH_CHARS:
        text = text.replace(dash, "-")
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"\s*\.\s*", ".", text)  # "gr1 . loumbila" -> "gr1.loumbila"
    text = re.sub(r"\s*-\s*", "-", text)
    return text


_ID_CANDIDATE_RE = re.compile(
    r"gr\s*[a-z0-9]{1,4}[\s.\-–—_]{1,3}[a-z0-9][a-z0-9\s\-–—_]{2,60}", re.IGNORECASE
)


def find_id_candidates(text: str) -> list[str]:
    """Recherche, dans un texte OCR complet (potentiellement multi-lignes), les
    segments ressemblant a un identifiant de groupe G50, sans se limiter a une
    seule regex rigide sur la totalite de la chaine."""
    candidates = []
    for match in _ID_CANDIDATE_RE.finditer(text):
        token = match.group(0).strip()
        token = re.split(r"[\n\r]", token)[0]
        if token:
            candidates.append(token)
    return candidates


def normalize_group_id(raw: str, known_ids: list[str] | None = None, fuzzy_threshold: int = 88) -> NormalizationResult:
    """Normalise un ID brut OCR et tente une correction floue contre les IDs connus."""
    if not raw or not raw.strip():
        return NormalizationResult(raw=raw or "", normalized=None, is_valid_format=False, confidence=0.0)

    corrections: list[str] = []
    text = _clean_text(raw)
    lowered = text.lower()

    prefix_match = re.match(r"^gr([a-z0-9]+)([.\-\s]?)(.*)$", lowered)
    if prefix_match:
        digits_part, _sep, rest = prefix_match.groups()
        fixed_digits = "".join(_DIGIT_CONFUSIONS.get(c, c) for c in text[2 : 2 + len(digits_part)])
        fixed_digits = fixed_digits.lower()
        if not fixed_digits.isdigit():
            fixed_digits = "".join(ch for ch in fixed_digits if ch.isdigit())
        if fixed_digits != digits_part:
            corrections.append(f"segment numerique '{digits_part}' -> '{fixed_digits}'")
        rest = rest.lstrip(".-")
        rest = re.sub(r"[^a-z0-9\-]", "", rest)
        rest = re.sub(r"-{2,}", "-", rest).strip("-")
        candidate = f"gr{fixed_digits}.{rest}" if fixed_digits and rest else None
    else:
        candidate = None

    is_valid = bool(candidate and ID_PATTERN.match(candidate))
    confidence = 1.0 if not corrections and is_valid else (0.75 if is_valid else 0.0)
    if is_valid and lowered != candidate:
        corrections.append(f"nettoyage separateurs: '{raw}' -> '{candidate}'")

    result = NormalizationResult(
        raw=raw,
        normalized=candidate if is_valid else None,
        is_valid_format=is_valid,
        corrections=corrections,
        confidence=confidence,
    )

    if known_ids:
        best_matches = process.extract(
            candidate or lowered, known_ids, scorer=fuzz.WRatio, limit=3
        )
        result.fuzzy_candidates = [(m[0], m[1]) for m in best_matches]
        if best_matches:
            top_id, top_score, _ = best_matches[0]
            second_score = best_matches[1][1] if len(best_matches) > 1 else 0.0
            if top_score >= fuzzy_threshold and (top_score - second_score) >= 5:
                result.fuzzy_match = top_id
                result.fuzzy_score = top_score
                if not is_valid or top_id != candidate:
                    result.requires_manual_review = top_id != candidate and top_score < 97
            elif top_score >= fuzzy_threshold:
                # Deux candidats trop proches : ne jamais choisir automatiquement.
                result.requires_manual_review = True

    if not is_valid and not result.fuzzy_match:
        result.requires_manual_review = True

    return result
