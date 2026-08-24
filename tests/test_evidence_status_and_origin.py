"""Tests API reels (TestClient) pour deux ajouts demandes apres retours
utilisateur : le changement manuel de statut depuis 'Preuves'
(PATCH /evidence/{id}/status, garde-fou sur les statuts autorises) et
l'affichage de l'origine WhatsApp (groupe) d'une preuve dans les reponses
de l'API evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.main import app
from app.models.evidence import EvidenceFile
from app.models.identity import Role, User, UserRole
from app.models.whatsapp import WhatsAppGroup, WhatsAppMessage


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def auth_token(db_session, client):
    role = Role(code=RoleCode.SUPER_ADMIN.value, name="Super administrateur")
    db_session.add(role)
    db_session.flush()
    user = User(
        email="ops@ges-g50.com",
        full_name="Operateur Test",
        hashed_password=hash_password("InitialPassw0rd!"),
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()

    login = client.post("/api/auth/login", json={"email": "ops@ges-g50.com", "password": "InitialPassw0rd!"})
    assert login.status_code == 200
    return login.json()["access_token"]


def _make_evidence(db_session, **overrides) -> EvidenceFile:
    evidence = EvidenceFile(
        original_filename=overrides.get("original_filename", "test.mp4"),
        stored_filename="stored-test.mp4",
        mime_type="video/mp4",
        media_type="video",
        file_size=1234,
        sha256="a" * 64,
        source="whatsapp_gateway",
        storage_path="uploads/test.mp4",
        processing_status=overrides.get("processing_status", "PENDING"),
    )
    db_session.add(evidence)
    db_session.commit()
    db_session.refresh(evidence)
    return evidence


def test_set_status_allows_completed(client, db_session, auth_token):
    evidence = _make_evidence(db_session, processing_status="FAILED")
    resp = client.patch(
        f"/api/evidence/{evidence.id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"status": "COMPLETED"},
    )
    assert resp.status_code == 200
    assert resp.json()["processing_status"] == "COMPLETED"


def test_set_status_rejects_transitional_states(client, db_session, auth_token):
    evidence = _make_evidence(db_session, processing_status="FAILED")
    for forbidden in ("PENDING", "QUEUED", "PROCESSING"):
        resp = client.patch(
            f"/api/evidence/{evidence.id}/status",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"status": forbidden},
        )
        assert resp.status_code == 400, f"{forbidden} aurait du etre refuse"

    # Le statut reel n'a pas bouge malgre les tentatives refusees.
    check = client.get(f"/api/evidence/{evidence.id}", headers={"Authorization": f"Bearer {auth_token}"})
    assert check.json()["processing_status"] == "FAILED"


def test_set_status_rejects_unknown_value(client, db_session, auth_token):
    evidence = _make_evidence(db_session)
    resp = client.patch(
        f"/api/evidence/{evidence.id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"status": "PAS_UN_VRAI_STATUT"},
    )
    assert resp.status_code == 400


def test_evidence_list_includes_whatsapp_group_origin(client, db_session, auth_token):
    evidence = _make_evidence(db_session)
    group = WhatsAppGroup(whatsapp_group_external_id="12345@g.us", name="Groupe Test Karangasso")
    db_session.add(group)
    db_session.flush()
    message = WhatsAppMessage(
        whatsapp_message_id="msg-1",
        group_id=group.id,
        group_external_id=group.whatsapp_group_external_id,
        message_date=datetime.now(UTC),
        evidence_id=evidence.id,
    )
    db_session.add(message)
    db_session.commit()

    resp = client.get("/api/evidence", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == evidence.id)
    assert row["whatsapp_group_name"] == "Groupe Test Karangasso"
    assert row["whatsapp_group_external_id"] == "12345@g.us"


def test_evidence_without_whatsapp_message_has_null_origin(client, db_session, auth_token):
    evidence = _make_evidence(db_session)
    resp = client.get(f"/api/evidence/{evidence.id}", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    assert resp.json()["whatsapp_group_name"] is None
