# ruff: noqa: F811
from datetime import UTC, datetime

import pytest

from app.api.routers.assistant import ChatRequest, resolve_period
from app.core.config import get_settings
from tests.test_evidence_status_and_origin import auth_token, client  # noqa: F401


def test_missing_period_asks_without_query_or_groq(client, auth_token, monkeypatch):
    monkeypatch.setattr(get_settings(), 'groq_assistant_enabled', True)
    monkeypatch.setattr(get_settings(), 'groq_api_key', 'fake')
    monkeypatch.setattr('app.api.routers.assistant.groq_json', lambda *a: pytest.fail('No inference before period choice'))
    monkeypatch.setattr('app.api.routers.assistant.data_or_error', lambda *a: pytest.fail('No report query before clarification'))
    result = client.post('/api/assistant/chat', headers={'Authorization': f'Bearer {auth_token}'}, json={
        'message': 'combien de personnes ont des rapports non valides', 'start': '2026-09-21', 'end': '2026-09-21'})
    assert result.status_code == 200
    assert result.json()['action'] == 'clarify'
    assert result.json()['data'] is None
    assert len(result.json()['clarification']['options']) == 4
    assert result.json()['drafts'] == []


@pytest.mark.parametrize('message,expected', [('rapports cette semaine', 'week'), ('rapports ce mois', 'month'),
                                             ("rapports aujourd’hui", 'day'), ("tout l’historique", 'all')])
def test_natural_period_resolves_real_dates(message, expected):
    payload = ChatRequest(message=message, start='2000-01-01', end='2000-01-01')
    resolved, question = resolve_period(payload)
    today = datetime.now(UTC).date()
    assert question is None
    assert resolved.end == today
    if expected == 'week':
        assert resolved.start.weekday() == 0
    elif expected == 'month':
        assert resolved.start.day == 1
    elif expected == 'all':
        assert resolved.scope == 'all'
    else:
        assert resolved.start == today


def test_ambiguous_task_after_period_still_does_not_execute(client, auth_token, monkeypatch):
    monkeypatch.setattr(get_settings(), 'groq_assistant_enabled', True)
    monkeypatch.setattr(get_settings(), 'groq_api_key', 'fake')
    monkeypatch.setattr('app.api.routers.assistant.groq_json',
                        lambda *a: {'clarification': 'Voulez-vous un export ou des relances ?'})
    monkeypatch.setattr('app.api.routers.assistant.data_or_error', lambda *a: pytest.fail('No query for ambiguous task'))
    result = client.post('/api/assistant/chat', headers={'Authorization': f'Bearer {auth_token}'}, json={
        'message': 'fais le nécessaire', 'scope': 'all', 'start': '2026-09-21', 'end': '2026-09-21'})
    assert result.json()['action'] == 'clarify'
    assert result.json()['data'] is None
