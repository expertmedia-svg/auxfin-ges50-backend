# ruff: noqa: F811
from app.core.config import get_settings
from app.services.operations import OperationQuery, operational_data
from tests.test_evidence_status_and_origin import auth_token, client  # noqa: F401
from tests.test_followups import make_report


def test_invalid_reports_override_wrong_coverage_plan_without_assignments(db_session, client, auth_token, monkeypatch):
    for _ in range(3):
        make_report(db_session, day="2026-09-14")
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    calls = []
    def groq(*args):
        calls.append(1)
        return {"dataset": "coverage", "status": "MISSING", "scope": "selected"}
    monkeypatch.setattr("app.api.routers.assistant.groq_json", groq)
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": "combien de personne on des rapport non valide", "scope": "all", "start": "2026-09-21", "end": "2026-09-21"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['data']['total'] == 3
    assert data['data']['review_queue_count'] == 3
    assert data['data']['unregistered_contacts_count'] == 1
    assert data['data']['registered_agents_count'] == 0
    assert '3 rapport(s)' in data['answer']
    assert len(calls) == 1  # Le modèle ne réécrit pas les chiffres calculés.


def test_general_report_count_uses_received_files_without_assignments(db_session, client, auth_token, monkeypatch):
    make_report(db_session, day="2026-09-21")
    make_report(db_session, day="2026-09-21", confirmed=True)
    make_report(db_session, day="2026-09-14")
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    monkeypatch.setattr("app.api.routers.assistant.groq_json", lambda *a: {
        "dataset": "coverage", "status": "MISSING"})
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": "combien de rapport", "scope": "selected", "start": "2026-09-21", "end": "2026-09-21"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['data']['query']['dataset'] == 'evidence'
    assert result['data']['total'] == 2
    assert 'affectation' not in result['answer']


def test_explicit_period_remains_applied(db_session):
    make_report(db_session, day="2026-09-14")
    query = OperationQuery(dataset="evidence", scope="selected", status="TO_REVIEW",
                           start="2026-09-21", end="2026-09-21")
    assert operational_data(db_session, query)['total'] == 0
    query.scope = "all"
    assert operational_data(db_session, query)['total'] == 1


def test_no_assignments_is_unavailable_not_zero_people(db_session, client, auth_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    monkeypatch.setattr("app.api.routers.assistant.groq_json", lambda *a: {"dataset": "coverage"})
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": "Qui devait soumettre ?", "scope": "selected", "start": "2026-09-21", "end": "2026-09-21"})
    assert response.status_code == 200
    assert response.json()['data']['coverage_available'] is False
    assert 'Aucun participant identifiable' in response.json()['answer']


def test_assistant_explains_review_reasons_for_one_evidence(db_session, client, auth_token, monkeypatch):
    ev = make_report(db_session, group=None, day=None)
    monkeypatch.setattr(get_settings(), "groq_assistant_enabled", True)
    monkeypatch.setattr(get_settings(), "groq_api_key", "fake")
    monkeypatch.setattr("app.api.routers.assistant.groq_json", lambda *a: {
        "dataset": "evidence", "evidence_id": ev.id})
    response = client.post('/api/assistant/chat', headers={"Authorization": f"Bearer {auth_token}"}, json={
        "message": f"Pourquoi cette preuve {ev.id} est à vérifier ?", "scope": "all",
        "start": "2026-09-21", "end": "2026-09-21"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['data']['total'] == 1
    assert 'Date du rapport absente ou ambiguë' in result['answer']
    assert 'Identifiant du groupe absent ou illisible' in result['answer']
    assert 'Synchronisation non confirmée' in result['answer']
