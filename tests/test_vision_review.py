from datetime import date

import pytest

from app.models.enums import SyncStatus
from app.services.vision import extraction_pipeline as pipeline
from app.services.vision.ocr_engine import OcrEngineResult
from app.services.vision.sync_status import detect_sync_status
from tests.test_status_icon import FIXTURES_DIR, YEBCOACH_ICON_ZONE


@pytest.mark.parametrize("text", ["Synchroniser", "Synchroniser à nouveau", "unsuccessful"])
def test_substrings_do_not_confirm(text):
    assert detect_sync_status(text, ["synchronise", "success"], []).status == SyncStatus.UNCONFIRMED


@pytest.mark.parametrize("text,status", [
    ("non synchronisé", SyncStatus.FAILED), ("not synchronized", SyncStatus.FAILED),
    ("Synchronisation en cours", SyncStatus.UNCONFIRMED), ("pending", SyncStatus.UNCONFIRMED),
])
def test_negative_and_pending_status(text, status):
    assert detect_sync_status(text, ["synchronise", "synchronized"], []).status == status


def mock_ocr(monkeypatch, confidence, text="gr1.kar-sam-samatoukoro 14/09/2026 Synchroniser"):
    monkeypatch.setattr(pipeline, "run_ocr_on_image_path", lambda _: [
        OcrEngineResult("test", "original", text, confidence)
    ])


def test_still_image_uses_application_icon(monkeypatch):
    mock_ocr(monkeypatch, 0.95)
    outcome = pipeline.extract_from_image(str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"),
                                          ["synchronisation reussie"], ["echec"],
                                          context_date=date(2026, 9, 14), status_icon_zone=YEBCOACH_ICON_ZONE)
    assert outcome.sync_status == SyncStatus.SUCCESS
    assert not outcome.requires_manual_review, outcome.review_reasons
    assert outcome.frame_debug[0].raw_text


def test_green_icon_does_not_clear_low_quality_review(monkeypatch):
    mock_ocr(monkeypatch, 0.2)
    outcome = pipeline.extract_from_image(str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"),
                                          ["synchronisation reussie"], ["echec"],
                                          context_date=date(2026, 9, 14), status_icon_zone=YEBCOACH_ICON_ZONE)
    assert outcome.sync_status == SyncStatus.SUCCESS
    assert outcome.requires_manual_review
    assert any("lisible" in reason for reason in outcome.review_reasons)


def test_pending_text_is_not_overridden_by_green(monkeypatch):
    mock_ocr(monkeypatch, 0.95, "gr1.kar-sam-samatoukoro 14/09/2026 synchronisation en cours")
    outcome = pipeline.extract_from_image(str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg"),
                                          [], [], status_icon_zone=YEBCOACH_ICON_ZONE)
    assert outcome.sync_status == SyncStatus.UNCONFIRMED
    assert outcome.requires_manual_review


def test_groq_disabled_never_contacts_network(monkeypatch):
    from app.core.config import get_settings
    from app.services.vision.groq_vision import transcribe
    monkeypatch.setattr(get_settings(), "groq_vision_enabled", False)
    monkeypatch.setattr("httpx.Client", lambda **_: pytest.fail("Unexpected network call"))
    assert transcribe("missing.jpg") is None


@pytest.mark.parametrize("texts,expected", [
    (["en cours", "synchronisation reussie"], SyncStatus.SUCCESS),
    (["synchronisation reussie", "echec"], SyncStatus.FAILED),
    (["synchronisation reussie", "en cours"], SyncStatus.UNCONFIRMED),
])
def test_video_uses_latest_explicit_state(monkeypatch, texts, expected):
    mock_ocr(monkeypatch, 0.9)
    outcome = pipeline.extract_from_image("unused", [], [])
    outcome.frame_debug = [pipeline.FrameOcrDebug("end", 8 - i, "unused", text, 0.9)
                           for i, text in enumerate(texts)]
    # Le texte de début ne doit jamais confirmer la fin.
    outcome.frame_debug.append(pipeline.FrameOcrDebug("start", 0, "unused", "synchronisation reussie", 0.9))
    pipeline.evaluate_sync_frames(outcome, ["synchronisation reussie"], ["echec"])
    assert outcome.sync_status == expected


def test_groq_contract_and_invalid_response_fallback(monkeypatch):
    import httpx

    from app.core.config import get_settings
    from app.services.vision import groq_vision

    monkeypatch.setattr(get_settings(), "groq_vision_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    responses = ['{"text":"gr1.test 14/09/2026","readable":true}', 'invalid json']
    def handler(request):
        assert request.url.host == "api.groq.com"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": responses.pop(0)}}]})
    factory = httpx.Client
    monkeypatch.setattr(groq_vision.httpx, "Client", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))
    path = str(FIXTURES_DIR / "yebcoach_sync_confirmed_green.jpg")
    assert groq_vision.transcribe(path) == "gr1.test 14/09/2026"
    assert groq_vision.transcribe(path) is None
