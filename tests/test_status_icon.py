"""Tests de detection du statut de synchronisation par couleur d'icone
(Phase C) : cas reel trouve en testant une vraie video YEBCoach envoyee via
WhatsApp — la confirmation de synchronisation n'est jamais exprimee par un
mot-cle textuel, seulement par une icone qui devient verte a cote du bouton
"Synchroniser". Les fixtures sont de vraies frames extraites de cette vraie
video (tests/fixtures/status_icons/), pas des images de synthese."""

from __future__ import annotations

from pathlib import Path

from app.services.vision.status_icon import detect_status_icon_color

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "status_icons"

# Zones calibrees reellement (voir scripts/seed_config.py) : mesurees
# directement sur les frames ou l'icone verte est visible.
YEBCOACH_ICON_ZONE = {"x": 0.78, "y": 0.30, "w": 0.09, "h": 0.11}
PFNLCOACH_ICON_ZONE = {"x": 0.48, "y": 0.20, "w": 0.11, "h": 0.13}
FINANCECOACH_ICON_ZONE = {"x": 0.83, "y": 0.27, "w": 0.07, "h": 0.11}


def test_detects_green_icon_on_real_confirmed_frame():
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"), YEBCOACH_ICON_ZONE
    )
    assert result.is_green is True
    assert result.green_ratio > 0.08


def test_does_not_detect_green_on_pending_frame():
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "yebcoach_sync_pending.jpg"), YEBCOACH_ICON_ZONE
    )
    assert result.is_green is False


def test_does_not_false_positive_on_final_menu_with_unrelated_red_button():
    """Regression : la derniere frame (menu Usage/Academie) contient un gros
    bouton rouge "Telecharger" dans la meme zone d'ecran generale — ne doit
    jamais etre confondu avec une icone verte de confirmation."""
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "yebcoach_final_menu_with_red_button.jpg"), YEBCOACH_ICON_ZONE
    )
    assert result.is_green is False


def test_empty_zone_returns_not_green():
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"), {"x": 0, "y": 0, "w": 0, "h": 0}
    )
    assert result.is_green is False
    assert result.green_ratio == 0.0


def test_detects_green_icon_on_real_pfnlcoach_upload_confirmed_frame():
    """Icone plus petite relativement a sa zone que YEBCoach (ratio ~0.065-
    0.071 observe reellement) : verifie que le seuil calibre la detecte quand
    meme, tout en restant strictement superieur a zero pour rester honnete."""
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "pfnlcoach_upload_confirmed_green.jpg"), PFNLCOACH_ICON_ZONE
    )
    assert result.is_green is True
    assert 0.05 <= result.green_ratio <= 0.10


def test_does_not_detect_green_on_pfnlcoach_frame_before_upload():
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "pfnlcoach_start_before_upload.jpg"), PFNLCOACH_ICON_ZONE
    )
    assert result.is_green is False


def test_detects_green_badge_on_real_financecoach_confirmed_frame():
    """FinanceCoach a aussi une case "Telecharger" cochee en BLEU, mais sa
    couleur seule ne distingue pas coche/vide (contour bleu de surface
    similaire dans les deux cas) — le petit badge vert a cote de
    "Synchroniser", present uniquement quand la synchronisation est
    confirmee, est le signal reellement fiable ici."""
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "financecoach_sync_confirmed_green.jpg"), FINANCECOACH_ICON_ZONE
    )
    assert result.is_green is True


def test_does_not_detect_green_on_financecoach_frame_before_sync():
    result = detect_status_icon_color(
        str(FIXTURES_DIR / "financecoach_start_before_sync.jpg"), FINANCECOACH_ICON_ZONE
    )
    assert result.is_green is False
