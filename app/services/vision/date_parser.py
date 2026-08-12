"""Detection et normalisation de dates lues par OCR sur les preuves eCoach.

Formats geres : 30/07/2026, 30-07-2026, 2026-07-30, "30 juillet 2026",
"Jeudi 30 juillet" (sans annee), "Thursday 30 July", "30 Jul 2026".
Aucune date n'est inventee : si l'annee est absente et qu'aucune date de
contexte fiable n'est fournie, le resultat reste non confirme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import dateparser

_MONTHS_FR = (
    "janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|"
    "septembre|octobre|novembre|decembre|décembre"
)
_MONTHS_EN = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

_DATE_CANDIDATE_RE = re.compile(
    r"("
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\d{1,2}\s*,?\s*(?:" + _MONTHS_FR + r")\.?\s*,?\s*\d{0,4}"
    r"|\d{1,2}\s*,?\s*(?:" + _MONTHS_EN + r")\.?\s*,?\s*\d{0,4}"
    r")",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"(19|20)\d{2}")


@dataclass
class DateParseResult:
    raw_text: str | None
    normalized_date: str | None  # ISO yyyy-mm-dd
    is_ambiguous: bool
    missing_year: bool
    confidence: float
    notes: list[str]


def _clean_candidate(text: str) -> str:
    text = text.strip().strip(",")
    text = text.replace(",", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def find_date_candidates(text: str) -> list[str]:
    return [_clean_candidate(m.group(0)) for m in _DATE_CANDIDATE_RE.finditer(text)]


def parse_date(
    text: str, context_date: date | None = None, languages: list[str] | None = None
) -> DateParseResult:
    """Tente d'extraire et de normaliser une date depuis un texte OCR brut."""
    candidates = find_date_candidates(text)
    if not candidates:
        return DateParseResult(
            raw_text=None,
            normalized_date=None,
            is_ambiguous=True,
            missing_year=False,
            confidence=0.0,
            notes=["Aucun motif de date detecte dans le texte OCR"],
        )

    raw_candidate = candidates[0]
    missing_year = _YEAR_RE.search(raw_candidate) is None

    settings: dict = {"STRICT_PARSING": False}
    is_iso_format = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_candidate))
    is_numeric_only = bool(re.fullmatch(r"[\d/\-\s]+", raw_candidate))
    if is_numeric_only and not is_iso_format:
        # DD/MM prioritaire (convention francophone/Burkina Faso) uniquement
        # pour les dates purement numeriques ambigues : forcer DATE_ORDER sur
        # un format ISO non ambigu (AAAA-MM-JJ) fait echouer dateparser.
        settings["DATE_ORDER"] = "DMY"
    if context_date is not None:
        settings["RELATIVE_BASE"] = datetime.combine(context_date, datetime.min.time())

    parsed = dateparser.parse(
        raw_candidate, languages=languages or ["fr", "en"], settings=settings
    )

    notes: list[str] = []
    if parsed is None:
        return DateParseResult(
            raw_text=raw_candidate,
            normalized_date=None,
            is_ambiguous=True,
            missing_year=missing_year,
            confidence=0.0,
            notes=["Le motif de date n'a pas pu etre interprete (probablement langue non supportee)"],
        )

    confidence = 0.9
    is_ambiguous = False

    if missing_year:
        if context_date is not None:
            parsed = parsed.replace(year=context_date.year)
            notes.append(
                f"Annee absente sur la preuve : deduite du contexte ({context_date.year})"
            )
            confidence = 0.6
            is_ambiguous = True
        else:
            notes.append("Annee absente et aucune date de contexte disponible : date non confirmee")
            return DateParseResult(
                raw_text=raw_candidate,
                normalized_date=None,
                is_ambiguous=True,
                missing_year=True,
                confidence=0.0,
                notes=notes,
            )

    return DateParseResult(
        raw_text=raw_candidate,
        normalized_date=parsed.date().isoformat(),
        is_ambiguous=is_ambiguous,
        missing_year=missing_year,
        confidence=confidence,
        notes=notes,
    )
