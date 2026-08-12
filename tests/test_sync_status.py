from app.models.enums import SyncStatus
from app.services.vision.sync_status import detect_sync_status

SUCCESS_KW = ["synchronisation reussie", "success", "completed"]
ERROR_KW = ["echec", "error", "failed"]


def test_detects_success_keyword():
    result = detect_sync_status("Synchronisation reussie !", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.SUCCESS


def test_detects_error_keyword():
    result = detect_sync_status("Une erreur est survenue: Failed", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.FAILED


def test_no_keyword_is_unconfirmed():
    result = detect_sync_status("Bouton Synchroniser visible a l'ecran", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.UNCONFIRMED


def test_button_label_alone_does_not_imply_success():
    # Le simple mot "Synchroniser" ne doit jamais suffire (regle imposee).
    result = detect_sync_status("Synchroniser", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.UNCONFIRMED


def test_error_takes_priority_over_success_if_both_present():
    result = detect_sync_status("completed but then Failed", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.FAILED


def test_empty_text_is_unconfirmed():
    result = detect_sync_status("", SUCCESS_KW, ERROR_KW)
    assert result.status == SyncStatus.UNCONFIRMED


def test_similar_but_distinct_word_does_not_trigger_false_success():
    # Regression : sur une vraie video AgriCoach, l'OCR du bouton "Synchronize
    # data again" (resynchroniser, PAS un succes) a ete lu "Synchronlze ata
    # again" et confondu par erreur avec le mot-cle de succes "synchronized"
    # (edit distance de 1 caractere). Un succes ne doit jamais etre deduit
    # d'un mot-cle court isole a moins d'une correspondance quasi exacte.
    text = "Synchronlze\nata\nagain"
    success_kw = ["synchronized", "synchronise", "completed", "success"]
    error_kw = ["echec", "erreur", "failed", "error"]
    result = detect_sync_status(text, success_kw, error_kw)
    assert result.status == SyncStatus.UNCONFIRMED
