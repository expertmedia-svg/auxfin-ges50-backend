"""Tests de detection automatique d'application (Phase B, point 6), a
partir du texte OCR REEL produit par le pipeline sur les 4 vraies videos
fournies (aucune application n'etait indiquee a l'avance lors de ces
executions ; textes complets sauvegardes tels quels dans
tests/fixtures/ocr_samples/, aucune donnee inventee).

Regression du bug trouve pendant cette validation : la comparaison
`score > best.confidence` melangeait une echelle 0-100 (score brut) et
une echelle 0-1 (confidence = score/100), ce qui faisait retenir en
pratique le dernier candidat non nul evalue plutot que le veritable
meilleur score — 3 des 4 videos etaient mal detectees avant correction
(`app/services/vision/application_detector.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.vision.application_detector import detect_application

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocr_samples"

APPLICATIONS = [
    ("id-financecoach", "financecoach", "FinanceCoach", ["financecoach", "finance coach"]),
    ("id-pfnlcoach", "pfnlcoach", "PFNLCoach", ["pfnlcoach", "pfnl coach"]),
    ("id-yebcoach", "yebcoach", "YEBCoach", ["yeb", "yebcoach"]),
    ("id-agricoach", "agricoach", "AgriCoach", ["agricoach", "agri coach"]),
]


def _real_ocr_text(app_code: str) -> str:
    return (FIXTURES_DIR / f"{app_code}_real_ocr.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("expected_code", ["financecoach", "pfnlcoach", "agricoach", "yebcoach"])
def test_detects_correct_application_from_real_ocr_text(expected_code):
    text = _real_ocr_text(expected_code)
    result = detect_application(text, APPLICATIONS)
    assert result.application_code == expected_code


@pytest.mark.parametrize("expected_code", ["financecoach", "pfnlcoach", "agricoach", "yebcoach"])
def test_detection_is_independent_of_application_iteration_order(expected_code):
    """Regression directe du bug d'echelle : le meilleur candidat ne doit
    pas dependre de l'ordre d'iteration des applications/mots-cles."""
    text = _real_ocr_text(expected_code)
    forward = detect_application(text, APPLICATIONS)
    backward = detect_application(text, list(reversed(APPLICATIONS)))
    assert forward.application_code == backward.application_code == expected_code


def test_ambiguous_match_between_two_similar_scores_is_not_auto_selected():
    """Deux applications distinctes au coude-a-coude (ecart < AMBIGUITY_MARGIN)
    ne doivent jamais etre departagees arbitrairement par l'ordre d'iteration."""
    # Court extrait ou "FinanceCoach" et "YEBCoach" obtiennent un score fuzzy
    # tres proche (75.0 chacun) : aucune des deux ne doit etre choisie.
    ambiguous_text = "'aceCoach\nFR\neb"
    result = detect_application(ambiguous_text, APPLICATIONS)
    assert result.application_code is None


def test_no_match_below_threshold_returns_none():
    result = detect_application("texte totalement sans rapport avec aucune application", APPLICATIONS)
    assert result.application_code is None


def test_empty_text_returns_none():
    result = detect_application("", APPLICATIONS)
    assert result.application_code is None
    assert result.confidence == 0.0
