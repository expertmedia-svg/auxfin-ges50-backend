"""Tests reels (TestClient + FastAPI) de la passerelle WhatsApp (Phase C) :
webhooks entrants, dedup, mapping groupe->application, groupes non autorises,
permissions et plafond de relance. Le service Node whatsapp-gateway lui-meme
(session/QR/reconnexion reelles) n'est pas simule ici : voir
docs/RAPPORT_FINAL_PHASE_C_WHATSAPP.md pour le test d'integration reel avec
un compte WhatsApp."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.main import app
from app.models.applications import Application
from app.models.evidence import EvidenceFile
from app.models.identity import Role, User, UserRole
from app.models.whatsapp import WhatsAppGatewayStatus, WhatsAppGroup, WhatsAppMessage

settings = get_settings()
GATEWAY_TOKEN = settings.whatsapp_gateway_shared_secret


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _make_user(db_session, role_code: str, email: str) -> tuple[User, str]:
    role = db_session.query(Role).filter(Role.code == role_code).first()
    if role is None:
        role = Role(code=role_code, name=role_code)
        db_session.add(role)
        db_session.flush()
    user = User(
        email=email, full_name=email, hashed_password=hash_password("Passw0rd!Strong"),
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user, "Passw0rd!Strong"


def _login(client, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth_headers(client, db_session, role_code: str, email: str) -> dict:
    user, password = _make_user(db_session, role_code, email)
    token = _login(client, email, password)
    return {"Authorization": f"Bearer {token}"}


def _media_payload(
    tmp_path, db_session, *, message_id: str, group_external_id: str, content: bytes = b"fake-image-bytes"
) -> tuple[dict, object]:
    media_path = tmp_path / f"{message_id}.jpg"
    media_path.write_bytes(content)
    payload = {
        "whatsapp_message_id": message_id,
        "group_external_id": group_external_id,
        "group_name": "Groupe de test",
        "sender_external_id": "22370000000@c.us",
        "sender_name": "Agent Test",
        "sender_phone": "+223 70 00 00 00",
        "message_date": datetime.now(UTC).isoformat(),
        "message_type": "image",
        "caption_text": None,
        "media_external_id": message_id,
        "media_filename": f"{message_id}.jpg",
        "mime_type": "image/jpeg",
        "file_size": len(content),
        "sha256": None,
        "storage_path": str(media_path),
        "download_status": "DOWNLOADED",
    }
    return payload, media_path


def _disable_enqueue(monkeypatch):
    calls: list[str] = []

    def _fake_delay(evidence_id: str):
        calls.append(evidence_id)

    import app.workers.tasks as tasks_module

    monkeypatch.setattr(tasks_module.process_evidence_task, "delay", _fake_delay)
    return calls


def test_webhook_message_rejects_missing_or_wrong_token(client, tmp_path, db_session):
    payload, _ = _media_payload(tmp_path, db_session, message_id="m1", group_external_id="g1@g.us")

    response = client.post("/api/whatsapp/webhook/message", json=payload)
    assert response.status_code == 401

    response = client.post(
        "/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": "wrong-token"}
    )
    assert response.status_code == 401

    assert db_session.query(WhatsAppMessage).count() == 0


def test_webhook_message_from_unmonitored_group_is_unassigned(client, tmp_path, db_session, monkeypatch):
    calls = _disable_enqueue(monkeypatch)
    payload, _ = _media_payload(tmp_path, db_session, message_id="m2", group_external_id="g-unauthorized@g.us")

    response = client.post(
        "/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN}
    )
    assert response.status_code == 204

    message = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m2").one()
    assert message.download_status == "SKIPPED_UNAUTHORIZED_GROUP"
    assert message.evidence_id is None
    assert db_session.query(EvidenceFile).count() == 0
    assert calls == []

    read_headers = _auth_headers(client, db_session, RoleCode.LECTEUR.value, "reader1@test.com")
    unassigned = client.get("/api/whatsapp/messages/unassigned", headers=read_headers)
    assert unassigned.status_code == 200
    assert any(m["whatsapp_message_id"] == "m2" for m in unassigned.json())


def test_webhook_message_monitored_group_creates_evidence_with_group_application(
    client, tmp_path, db_session, monkeypatch
):
    calls = _disable_enqueue(monkeypatch)

    application = Application(code="agricoach-test", name="AgriCoach Test")
    db_session.add(application)
    db_session.flush()
    group = WhatsAppGroup(
        whatsapp_group_external_id="g-monitored@g.us", name="G50 Kar", is_monitored=True,
        application_id=application.id,
    )
    db_session.add(group)
    db_session.commit()

    payload, _ = _media_payload(tmp_path, db_session, message_id="m3", group_external_id="g-monitored@g.us")
    response = client.post(
        "/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN}
    )
    assert response.status_code == 204

    message = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m3").one()
    assert message.download_status == "DOWNLOADED"
    assert message.evidence_id is not None

    evidence = db_session.get(EvidenceFile, message.evidence_id)
    assert evidence.source == "whatsapp_gateway"
    assert evidence.application_id == application.id  # mapping groupe -> application, pas d'auto-detection
    assert evidence.processing_status != "DUPLICATE"
    assert calls == [evidence.id]  # pipeline OCR bien declenche


def test_webhook_message_duplicate_media_is_flagged_and_not_reenqueued(client, tmp_path, db_session, monkeypatch):
    calls = _disable_enqueue(monkeypatch)

    group = WhatsAppGroup(whatsapp_group_external_id="g-dup@g.us", name="G50 Dup", is_monitored=True)
    db_session.add(group)
    db_session.commit()

    same_bytes = b"identical-media-content-for-dedup-test"
    payload1, _ = _media_payload(tmp_path, db_session, message_id="m4a", group_external_id="g-dup@g.us", content=same_bytes)
    response1 = client.post("/api/whatsapp/webhook/message", json=payload1, headers={"X-Gateway-Token": GATEWAY_TOKEN})
    assert response1.status_code == 204

    payload2, _ = _media_payload(tmp_path, db_session, message_id="m4b", group_external_id="g-dup@g.us", content=same_bytes)
    response2 = client.post("/api/whatsapp/webhook/message", json=payload2, headers={"X-Gateway-Token": GATEWAY_TOKEN})
    assert response2.status_code == 204

    msg1 = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m4a").one()
    msg2 = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m4b").one()
    evidence1 = db_session.get(EvidenceFile, msg1.evidence_id)
    evidence2 = db_session.get(EvidenceFile, msg2.evidence_id)

    assert evidence1.processing_status != "DUPLICATE"
    assert evidence2.processing_status == "DUPLICATE"
    assert evidence2.is_duplicate_of_id == evidence1.id
    assert calls == [evidence1.id]  # le doublon n'est jamais envoye a l'OCR


def test_webhook_message_is_idempotent_on_same_message_id(client, tmp_path, db_session, monkeypatch):
    calls = _disable_enqueue(monkeypatch)
    group = WhatsAppGroup(whatsapp_group_external_id="g-idem@g.us", name="G50 Idem", is_monitored=True)
    db_session.add(group)
    db_session.commit()

    payload, _ = _media_payload(tmp_path, db_session, message_id="m5", group_external_id="g-idem@g.us")
    for _ in range(2):
        response = client.post(
            "/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN}
        )
        assert response.status_code == 204

    assert db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m5").count() == 1
    assert len(calls) == 1  # jamais reenqueue pour le meme message


def test_webhook_message_skipped_no_media_creates_no_evidence(client, db_session, monkeypatch):
    calls = _disable_enqueue(monkeypatch)
    group = WhatsAppGroup(whatsapp_group_external_id="g-nomedia@g.us", name="G50 NoMedia", is_monitored=True)
    db_session.add(group)
    db_session.commit()

    payload = {
        "whatsapp_message_id": "m6",
        "group_external_id": "g-nomedia@g.us",
        "group_name": "G50 NoMedia",
        "sender_name": "Agent Test",
        "message_date": datetime.now(UTC).isoformat(),
        "message_type": "other",
        "download_status": "FAILED",
        "last_error": "Media temporairement indisponible",
    }
    response = client.post(
        "/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN}
    )
    assert response.status_code == 204

    message = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m6").one()
    assert message.evidence_id is None
    assert calls == []


def test_webhook_status_updates_gateway_status_row(client, db_session):
    payload = {
        "connection_state": "CONNECTED",
        "phone_number": "22370000000",
        "display_name": "Bot GES-G50",
        "last_error": None,
        "connected_at": datetime.now(UTC).isoformat(),
    }
    response = client.post(
        "/api/whatsapp/webhook/status", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN}
    )
    assert response.status_code == 204
    assert db_session.query(WhatsAppGatewayStatus).count() == 1

    read_headers = _auth_headers(client, db_session, RoleCode.LECTEUR.value, "reader2@test.com")
    status_response = client.get("/api/whatsapp/status", headers=read_headers)
    assert status_response.status_code == 200
    assert status_response.json()["connection_state"] == "CONNECTED"
    assert status_response.json()["phone_number"] == "22370000000"


def test_retry_endpoint_respects_max_attempts(client, tmp_path, db_session, monkeypatch):
    _disable_enqueue(monkeypatch)
    group = WhatsAppGroup(whatsapp_group_external_id="g-retry@g.us", name="G50 Retry", is_monitored=True)
    db_session.add(group)
    db_session.commit()

    payload, _ = _media_payload(tmp_path, db_session, message_id="m7", group_external_id="g-retry@g.us")
    client.post("/api/whatsapp/webhook/message", json=payload, headers={"X-Gateway-Token": GATEWAY_TOKEN})

    message = db_session.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == "m7").one()
    message.retry_count = 5
    db_session.commit()

    write_headers = _auth_headers(client, db_session, RoleCode.SUPERVISEUR.value, "supervisor1@test.com")
    response = client.post(f"/api/whatsapp/messages/{message.id}/retry", headers=write_headers)
    assert response.status_code == 409


def test_group_permissions_require_admin_role(client, db_session):
    group = WhatsAppGroup(whatsapp_group_external_id="g-perm@g.us", name="G50 Perm", is_monitored=False)
    db_session.add(group)
    db_session.commit()

    reader_headers = _auth_headers(client, db_session, RoleCode.LECTEUR.value, "reader3@test.com")
    read_response = client.get("/api/whatsapp/groups", headers=reader_headers)
    assert read_response.status_code == 200

    forbidden = client.patch(
        f"/api/whatsapp/groups/{group.id}", json={"is_monitored": True}, headers=reader_headers
    )
    assert forbidden.status_code == 403

    admin_headers = _auth_headers(client, db_session, RoleCode.ADMIN.value, "admin1@test.com")
    allowed = client.patch(
        f"/api/whatsapp/groups/{group.id}", json={"is_monitored": True}, headers=admin_headers
    )
    assert allowed.status_code == 200
    assert allowed.json()["is_monitored"] is True


def test_connect_endpoint_requires_admin_role(client, db_session):
    reader_headers = _auth_headers(client, db_session, RoleCode.LECTEUR.value, "reader4@test.com")
    response = client.post("/api/whatsapp/connect", headers=reader_headers)
    assert response.status_code == 403
