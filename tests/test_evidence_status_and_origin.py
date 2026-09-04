"""Tests API reels (TestClient) pour deux ajouts demandes apres retours
utilisateur : le changement manuel de statut depuis 'Preuves'
(PATCH /evidence/{id}/status, garde-fou sur les statuts autorises) et
l'affichage de l'origine WhatsApp (groupe) d'une preuve dans les reponses
de l'API evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.main import app
from app.models.evidence import EvidenceExtraction, EvidenceFile
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
        stored_filename=overrides.get("stored_filename", "stored-test.mp4"),
        mime_type="video/mp4",
        media_type="video",
        file_size=1234,
        sha256=overrides.get("sha256", "a" * 64),
        source="whatsapp_gateway",
        storage_path="uploads/test.mp4",
        processing_status=overrides.get("processing_status", "PENDING"),
        sender_name=overrides.get("sender_name"),
        sender_phone=overrides.get("sender_phone"),
        received_at=overrides.get("received_at", datetime.now(UTC)),
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


def test_evidence_exposes_sender_phone(client, db_session, auth_token):
    evidence = _make_evidence(db_session, sender_phone="22670000000", sender_name="Amidou K.")
    resp = client.get(f"/api/evidence/{evidence.id}", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    assert resp.json()["sender_phone"] == "22670000000"
    assert resp.json()["sender_name"] == "Amidou K."


def test_export_ids_csv_contains_detected_id_and_contact(client, db_session, auth_token):
    evidence = _make_evidence(
        db_session,
        original_filename="today.mp4",
        sha256="b" * 64,
        stored_filename="stored-today.mp4",
        sender_phone="22670000001",
        sender_name="Fatou D.",
        received_at=datetime.now(UTC),
    )
    db_session.add(EvidenceExtraction(evidence_id=evidence.id, normalized_group_id="gr1.test-groupe"))
    db_session.commit()

    # Par defaut (detailed non fourni) : uniquement la colonne ID, tel que
    # demande explicitement par l'utilisateur ("juste la zone ID detecte").
    resp = client.get(
        "/api/evidence/export-ids",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"format": "csv"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.content.decode("utf-8-sig")
    assert "gr1.test-groupe" in body
    assert "22670000001" not in body
    assert "Fatou D." not in body

    # detailed=true : l'export complet (contact/telephone inclus) reste
    # disponible pour qui en a besoin.
    detailed_resp = client.get(
        "/api/evidence/export-ids",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"format": "csv", "detailed": "true"},
    )
    assert detailed_resp.status_code == 200
    detailed_body = detailed_resp.content.decode("utf-8-sig")
    assert "gr1.test-groupe" in detailed_body
    assert "22670000001" in detailed_body
    assert "Fatou D." in detailed_body


def test_export_ids_excludes_evidence_without_detected_id(client, db_session, auth_token):
    _make_evidence(db_session, original_filename="no-id.mp4", sha256="c" * 64, stored_filename="stored-no-id.mp4")
    resp = client.get(
        "/api/evidence/export-ids",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"format": "csv"},
    )
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert "no-id.mp4" not in body  # aucune extraction -> pas d'ID -> exclu


def test_export_ids_respects_period_filter(client, db_session, auth_token):
    old_evidence = _make_evidence(
        db_session,
        original_filename="old.mp4",
        sha256="d" * 64,
        stored_filename="stored-old.mp4",
        received_at=datetime.now(UTC) - timedelta(days=30),
    )
    db_session.add(EvidenceExtraction(evidence_id=old_evidence.id, normalized_group_id="gr2.hors-periode"))
    db_session.commit()

    today = date.today().isoformat()
    resp = client.get(
        "/api/evidence/export-ids",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"format": "csv", "period_start": today, "period_end": today},
    )
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert "gr2.hors-periode" not in body


def test_export_ids_xlsx_format(client, db_session, auth_token):
    evidence = _make_evidence(
        db_session, original_filename="xlsx.mp4", sha256="e" * 64, stored_filename="stored-xlsx.mp4"
    )
    db_session.add(EvidenceExtraction(evidence_id=evidence.id, normalized_group_id="gr3.excel-test"))
    db_session.commit()

    resp = client.get(
        "/api/evidence/export-ids",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"format": "xlsx"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(resp.content) > 0


def test_reject_removes_evidence_from_manual_review_queue(client, db_session, auth_token):
    """Bug reel : reject_evidence() ne mettait jamais a jour processing_status,
    donc une preuve rejetee restait indefiniment dans la file de controle
    manuel (le bouton 'Rejeter' semblait ne rien faire cote utilisateur)."""
    evidence = _make_evidence(db_session, processing_status="REQUIRES_REVIEW")

    resp = client.post(
        f"/api/evidence/{evidence.id}/reject",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"comment": "Pas une preuve valide"},
    )
    assert resp.status_code == 204

    db_session.refresh(evidence)
    assert evidence.processing_status == "FAILED"

    queue = client.get(
        "/api/evidence",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"requires_review": True},
    )
    assert evidence.id not in [e["id"] for e in queue.json()]


def test_validate_removes_evidence_from_manual_review_queue(client, db_session, auth_token):
    evidence = _make_evidence(db_session, processing_status="REQUIRES_REVIEW")

    resp = client.post(
        f"/api/evidence/{evidence.id}/validate",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"comment": None},
    )
    assert resp.status_code == 204

    db_session.refresh(evidence)
    assert evidence.processing_status == "COMPLETED"

    queue = client.get(
        "/api/evidence",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"requires_review": True},
    )
    assert evidence.id not in [e["id"] for e in queue.json()]
