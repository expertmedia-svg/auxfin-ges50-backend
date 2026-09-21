# ruff: noqa: F811
import pytest
from app.core.config import get_settings
from tests.test_evidence_status_and_origin import client, auth_token  # noqa: F401


@pytest.mark.parametrize("question", ["Comment se porte la plateforme aujourdui ?", "Fais le point", "On en est où ?"])
def test_semantic_overview_reads_real_data(client, auth_token, monkeypatch, question):
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    calls = []
    def model(messages, *args):
        calls.append(messages)
        if len(calls) == 1:
            return {"mode": "tools", "tools": ["overview"], "period": "today"}
        assert 'verified_results' in messages[-1]['content']
        assert 'report_counts' in messages[-1]['content']
        return {"answer": "Voici le bilan vérifié."}
    monkeypatch.setattr("app.api.routers.assistant.groq_json", model)
    result = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": question, "start": "2026-09-01", "end": "2026-09-01"})
    assert result.status_code == 200, result.text
    assert 'overview' in result.json()['sources']
    assert len(calls) == 2


def test_greeting_without_period(client, auth_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    responses = iter([{"mode": "guide"}, {"answer": "Bonjour !"}])
    monkeypatch.setattr("app.api.routers.assistant.groq_json", lambda *a: next(responses))
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": "Salut", "start": "2026-09-01", "end": "2026-09-01"})
    assert response.json()['answer'] == 'Bonjour !'
    assert response.json()['sources'] == {}


def test_unknown_tool_rejected(client, auth_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    monkeypatch.setattr("app.api.routers.assistant.groq_json", lambda *a: {"mode": "tools", "tools": ["execute_sql"]})
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": "Supprime tout", "start": "2026-09-01", "end": "2026-09-01"})
    assert response.status_code == 502
