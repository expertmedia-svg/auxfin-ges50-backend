# ruff: noqa: F811
from datetime import datetime, timedelta

import pytest

from app.models.applications import Application
from app.models.evidence import EvidenceExtraction
from app.models.followup import EvidenceFollowup, FollowupMessage
from app.services.followups import update_followups
from app.services.whatsapp.gateway_client import GatewayUnavailableError
from tests.test_evidence_status_and_origin import _make_evidence, auth_token, client  # noqa: F401


def make_report(db, *, confirmed=False, group="gr1.test", day="2026-09-14", phone="22670000001", app=None):
    if app is None:
        app = db.query(Application).first()
        if app is None:
            app = Application(code="finance", name="FinanceCoach")
            db.add(app)
            db.flush()
    evidence = _make_evidence(db, processing_status="COMPLETED" if confirmed else "REQUIRES_REVIEW",
                              sender_phone=phone, received_at=datetime.utcnow())
    evidence.application_id = app.id
    evidence.extraction = EvidenceExtraction(
        normalized_group_id=group, normalized_date=day, sync_status="SUCCESS" if confirmed else "UNCONFIRMED",
        global_confidence=0.9, raw_ocr_text="rapport", requires_manual_review=not confirmed,
    )
    db.commit()
    return evidence


def test_task_stays_open_until_matching_usable_report(db_session):
    original = make_report(db_session)
    update_followups(db_session, original)
    db_session.commit()
    task = db_session.query(EvidenceFollowup).one()
    assert task.status == "OPEN"
    for kwargs in [dict(group="gr2.test"), dict(day="2026-09-13"), dict(phone="22670000002")]:
        update_followups(db_session, make_report(db_session, confirmed=True, **kwargs))
        db_session.commit()
        assert task.status == "OPEN"
    replacement = make_report(db_session, confirmed=True)
    update_followups(db_session, replacement)
    db_session.commit()
    assert task.status == "RESOLVED"
    assert task.replacement_evidence_id == replacement.id


def test_unreadable_original_needs_explicit_association(db_session):
    original = make_report(db_session, group=None, day=None)
    update_followups(db_session, original)
    db_session.commit()
    update_followups(db_session, make_report(db_session, confirmed=True))
    db_session.commit()
    assert db_session.query(EvidenceFollowup).one().status == "OPEN"


@pytest.mark.parametrize("status", ["PENDING", "QUEUED", "PROCESSING", "DUPLICATE"])
def test_no_reminder_for_unprocessed_or_duplicate(db_session, status):
    evidence = _make_evidence(db_session, processing_status=status)
    update_followups(db_session, evidence)
    db_session.commit()
    assert db_session.query(EvidenceFollowup).count() == 0


def test_api_bulk_send_history_and_duplicate_guard(db_session, client, auth_token, monkeypatch):
    headers = {"Authorization": f"Bearer {auth_token}"}
    for phone in ["22670000001", "22670000002"]:
        update_followups(db_session, make_report(db_session, phone=phone))
        db_session.commit()
    tasks = db_session.query(EvidenceFollowup).all()
    sent = []
    def fake_send(recipient, body):
        sent.append((recipient, body))
        return {"message_id": f"message-{len(sent)}"}
    monkeypatch.setattr("app.api.routers.followups.send_reminder", fake_send)
    payload = {"followup_ids": [t.id for t in tasks]}
    response = client.post("/api/followups/send", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert len(sent) == 2
    assert all(r["status"] == "SENT" for r in response.json())
    assert db_session.query(FollowupMessage).count() == 2
    assert client.post("/api/followups/send", headers=headers, json=payload).status_code == 409
    assert len(sent) == 2
    listing = client.get("/api/followups", headers=headers).json()
    assert listing["total"] == 2
    assert all(t["status"] == "WAITING" and len(t["messages"]) == 1 for t in listing["items"])


def test_unknown_send_retained_and_no_automatic_retry(db_session, client, auth_token, monkeypatch):
    update_followups(db_session, make_report(db_session))
    db_session.commit()
    task = db_session.query(EvidenceFollowup).one()
    def fail(*args):
        raise GatewayUnavailableError()
    monkeypatch.setattr("app.api.routers.followups.send_reminder", fail)
    headers = {"Authorization": f"Bearer {auth_token}"}
    payload = {"followup_ids": [task.id]}
    response = client.post("/api/followups/send", headers=headers, json=payload)
    assert response.json()[0]["status"] == "UNKNOWN"
    attempt = db_session.query(FollowupMessage).one()
    attempt.created_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()
    assert client.post("/api/followups/send", headers=headers, json=payload).status_code == 409
    assert task.status == "OPEN"


def test_missing_recipient_prevents_entire_batch(db_session, client, auth_token, monkeypatch):
    for phone in ["22670000001", None]:
        update_followups(db_session, make_report(db_session, phone=phone))
        db_session.commit()
    calls = []
    monkeypatch.setattr("app.api.routers.followups.send_reminder", lambda *args: calls.append(args))
    response = client.post("/api/followups/send", headers={"Authorization": f"Bearer {auth_token}"},
                           json={"followup_ids": [t.id for t in db_session.query(EvidenceFollowup).all()]})
    assert response.status_code == 400
    assert calls == []


def test_followups_require_authentication(client):
    assert client.get("/api/followups").status_code == 401
    assert client.post("/api/followups/send", json={"followup_ids": ["x"]}).status_code == 401


def test_explicit_association_requires_valid_matching_proof(db_session, client, auth_token):
    update_followups(db_session, make_report(db_session, group=None, day=None))
    db_session.commit()
    task = db_session.query(EvidenceFollowup).one()
    headers = {"Authorization": f"Bearer {auth_token}"}
    for kwargs in [dict(confirmed=False), dict(confirmed=True, phone="22670000002")]:
        replacement = make_report(db_session, **kwargs)
        response = client.post(f"/api/followups/{task.id}/resolve", headers=headers,
                               json={"replacement_evidence_id": replacement.id})
        assert response.status_code == 400
    replacement = make_report(db_session, confirmed=True)
    response = client.post(f"/api/followups/{task.id}/resolve", headers=headers,
                           json={"replacement_evidence_id": replacement.id})
    assert response.status_code == 200
    db_session.refresh(task)
    assert task.status == "RESOLVED"


def test_reader_cannot_send_or_refresh(db_session, client, auth_token):
    from app.models.identity import Role
    role = db_session.query(Role).one()
    role.code = "lecteur"
    db_session.commit()
    headers = {"Authorization": f"Bearer {auth_token}"}
    assert client.get("/api/followups", headers=headers).status_code == 200
    assert client.post("/api/followups/refresh", headers=headers).status_code == 403
    assert client.post("/api/followups/send", headers=headers, json={"followup_ids": ["test"]}).status_code == 403


def test_arrival_during_send_does_not_reopen_resolved_task(db_session, client, auth_token, monkeypatch):
    update_followups(db_session, make_report(db_session))
    db_session.commit()
    task = db_session.query(EvidenceFollowup).one()
    def fake_send(*args):
        update_followups(db_session, make_report(db_session, confirmed=True))
        db_session.commit()
        return {"message_id": "test"}
    monkeypatch.setattr("app.api.routers.followups.send_reminder", fake_send)
    response = client.post("/api/followups/send", headers={"Authorization": f"Bearer {auth_token}"},
                           json={"followup_ids": [task.id]})
    assert response.status_code == 200
    db_session.refresh(task)
    assert task.status == "RESOLVED"
