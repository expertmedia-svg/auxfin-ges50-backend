"""Identification automatique de l'application eCoach a partir du texte OCR
(nom visible, mots-cles de logo) — section 12. Une correction manuelle reste
toujours possible et l'estimation automatique n'est jamais ecrasee silencieusement."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

DETECTION_THRESHOLD = 70
# Si les deux meilleures applications (distinctes) sont a moins de cet ecart
# l'une de l'autre, la detection est jugee ambigue : on ne choisit jamais
# automatiquement entre deux applications differentes qui se ressemblent
# trop (meme principe que la correction floue d'ID, section 9).
AMBIGUITY_MARGIN = 8


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


@dataclass
class ApplicationDetection:
    application_id: str | None
    application_code: str | None
    confidence: float


def detect_application(
    text: str, applications: list[tuple[str, str, str, list[str]]]
) -> ApplicationDetection:
    """`applications` est une liste de tuples (id, code, name, logo_keywords)."""
    folded_text = _fold(text)
    if not folded_text.strip():
        return ApplicationDetection(None, None, 0.0)

    # best_score reste sur l'echelle 0-100 (celle de fuzz.partial_ratio) tout
    # au long de la comparaison. Bug corrige (Phase B) : comparer directement
    # un score 0-100 a un ApplicationDetection.confidence 0-1 (score/100)
    # faisait qu'une comparaison "score > best.confidence" etait presque
    # toujours vraie (n'importe quel score >1 bat n'importe quelle fraction
    # <=1), donc le "meilleur" candidat retenu etait en pratique le dernier
    # candidat non nul evalue, pas le veritable maximum — 3 des 4 vraies
    # videos testees en detection automatique en etaient faussees.
    best_app_id: str | None = None
    best_app_code: str | None = None
    best_score = 0.0
    # Meilleur score obtenu par une application DIFFERENTE de la meilleure,
    # pour detecter les cas ambigus (deux apps distinctes au coude-a-coude).
    runner_up_score = 0.0

    for app_id, code, name, logo_keywords in applications:
        candidates = [name, code, *logo_keywords]
        app_best_score = 0.0
        for candidate in candidates:
            folded_candidate = _fold(candidate)
            if not folded_candidate:
                continue
            score = (
                100.0
                if folded_candidate in folded_text
                else fuzz.partial_ratio(folded_candidate, folded_text)
            )
            app_best_score = max(app_best_score, score)

        if app_best_score > best_score:
            runner_up_score = best_score
            best_score = app_best_score
            best_app_id = app_id
            best_app_code = code
        elif app_best_score > runner_up_score:
            runner_up_score = app_best_score

    if best_score < DETECTION_THRESHOLD:
        return ApplicationDetection(None, None, best_score / 100)
    if best_score - runner_up_score < AMBIGUITY_MARGIN:
        # Deux applications distinctes se ressemblent trop : verification
        # manuelle requise plutot qu'un choix automatique arbitraire.
        return ApplicationDetection(None, None, best_score / 100)
    return ApplicationDetection(best_app_id, best_app_code, best_score / 100)
