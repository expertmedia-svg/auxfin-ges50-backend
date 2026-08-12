"""Detection du statut de synchronisation (SUCCESS / FAILED / UNCONFIRMED) a partir
du texte OCR de fin d'ecran, en s'appuyant sur des mots-cles configurables par
application (ApplicationProfile.success_keywords / error_keywords).

Regle imposee par le cahier des charges : la simple presence d'un bouton
"Synchroniser" ne suffit jamais a conclure un succes. Un succes n'est retenu
que si un mot-cle de succes explicite est trouve ET qu'aucun mot-cle d'echec
n'est present.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.models.enums import SyncStatus

MATCH_THRESHOLD = 85
# Les mots-cles courts et isoles (ex: "synchronise") sont a une distance
# d'edition de 1-2 caracteres de mots tres frequents mais non probants (ex:
# "synchroniser", bouton omnipresent) : on exige une correspondance quasi
# exacte pour eux, faute de quoi une simple faute d'OCR sur un mot voisin
# suffirait a declencher un faux SUCCESS/FAILED.
SHORT_KEYWORD_MATCH_THRESHOLD = 95
SHORT_KEYWORD_MAX_LENGTH = 14


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("_", " ")
    return text.lower()


@dataclass
class SyncStatusResult:
    status: SyncStatus
    matched_keyword: str | None
    confidence: float


def _required_threshold(folded_keyword: str) -> float:
    is_single_short_word = (
        " " not in folded_keyword and len(folded_keyword) <= SHORT_KEYWORD_MAX_LENGTH
    )
    return SHORT_KEYWORD_MATCH_THRESHOLD if is_single_short_word else MATCH_THRESHOLD


def _best_keyword_match(folded_text: str, keywords: list[str]) -> tuple[str | None, float]:
    """Compare chaque mot-cle a des fenetres de mots de meme longueur dans le
    texte, avec fuzz.ratio (similarite globale symetrique). fuzz.partial_ratio
    a ete evite ici : il declare un score eleve des qu'un prefixe correspond
    (ex: "synchroniser" vs "synchronisation reussie" ~ 91%), ce qui validerait
    a tort une synchronisation sur la seule presence du bouton "Synchroniser"
    — interdit explicitement par le cahier des charges. Les mots-cles courts
    isoles doivent en plus depasser un seuil plus strict (cf. _required_threshold)
    pour ne pas etre confondus avec un mot voisin non probant (ex: "synchronise"
    vs "synchronize" dans un bouton "Synchronize again")."""
    words = folded_text.split()
    best_keyword: str | None = None
    best_score = 0.0
    # Marge au-dessus du seuil requis, pour comparer des mots-cles a seuils differents.
    best_effective_score = 0.0
    for keyword in keywords:
        folded_keyword = _fold(keyword)
        if not folded_keyword:
            continue
        if folded_keyword in folded_text:
            score = 100.0
        else:
            keyword_word_count = max(len(folded_keyword.split()), 1)
            score = 0.0
            for i in range(max(len(words) - keyword_word_count + 1, 1)):
                window = " ".join(words[i : i + keyword_word_count])
                if window:
                    score = max(score, fuzz.ratio(folded_keyword, window))

        required = _required_threshold(folded_keyword)
        if score < required:
            continue
        effective_score = score - required
        if effective_score >= best_effective_score or best_keyword is None:
            best_effective_score = effective_score
            best_score = score
            best_keyword = keyword
    return best_keyword, best_score


def detect_sync_status(
    text: str, success_keywords: list[str], error_keywords: list[str]
) -> SyncStatusResult:
    if not text or not text.strip():
        return SyncStatusResult(status=SyncStatus.UNCONFIRMED, matched_keyword=None, confidence=0.0)

    folded_text = _fold(text)

    # _best_keyword_match ne retourne un mot-cle que s'il a deja franchi son
    # propre seuil requis (standard ou renforce pour les mots courts isoles).
    error_keyword, error_score = _best_keyword_match(folded_text, error_keywords)
    if error_keyword:
        return SyncStatusResult(
            status=SyncStatus.FAILED, matched_keyword=error_keyword, confidence=error_score / 100
        )

    success_keyword, success_score = _best_keyword_match(folded_text, success_keywords)
    if success_keyword:
        return SyncStatusResult(
            status=SyncStatus.SUCCESS, matched_keyword=success_keyword, confidence=success_score / 100
        )

    return SyncStatusResult(status=SyncStatus.UNCONFIRMED, matched_keyword=None, confidence=0.0)
