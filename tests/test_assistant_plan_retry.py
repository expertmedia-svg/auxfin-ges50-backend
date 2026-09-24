import pytest
from app.api.routers import assistant


def test_invalid_plan_is_retried_once(monkeypatch):
    calls = []
    def respond(messages, model, key):
        calls.append(messages)
        return {"answer": "Bonjour"} if len(calls) == 1 else {"mode": "guide"}
    monkeypatch.setattr(assistant, "groq_json", respond)
    assert assistant.groq_plan([], "model", "key").mode == "guide"
    assert len(calls) == 2


def test_invalid_plan_never_becomes_an_action(monkeypatch):
    calls = []
    def respond(*args):
        calls.append(1)
        return {"action": "send_messages"}
    monkeypatch.setattr(assistant, "groq_json", respond)
    with pytest.raises(ValueError):
        assistant.groq_plan([], "model", "key")
    assert len(calls) == 2
