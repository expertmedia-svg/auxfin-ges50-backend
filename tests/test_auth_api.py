"""Tests API reels (TestClient + FastAPI) du flux d'authentification :
verrouillage de compte apres echecs repetes et changement de mot de passe
obligatoire (Phase B, section 8)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.main import app
from app.models.identity import Role, User, UserRole


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
def seeded_user(db_session):
    role = Role(code=RoleCode.SUPER_ADMIN.value, name="Super administrateur")
    db_session.add(role)
    db_session.flush()

    user = User(
        email="test-admin@ges-g50.com",
        full_name="Test Admin",
        hashed_password=hash_password("InitialPassw0rd!"),
        must_change_password=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


def test_login_success_reports_must_change_password(client, seeded_user):
    response = client.post(
        "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "InitialPassw0rd!"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True


def test_change_password_clears_flag_and_invalidates_old_password(client, seeded_user):
    login = client.post(
        "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "InitialPassw0rd!"}
    )
    token = login.json()["access_token"]

    change = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "InitialPassw0rd!", "new_password": "BrandNewPassw0rd!"},
    )
    assert change.status_code == 204

    old_login = client.post(
        "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "InitialPassw0rd!"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "BrandNewPassw0rd!"}
    )
    assert new_login.status_code == 200
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {new_login.json()['access_token']}"}
    )
    assert me.json()["must_change_password"] is False


def test_account_locks_after_max_failed_attempts(client, seeded_user):
    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "wrong-password"}
        )
        assert response.status_code == 401

    locked_response = client.post(
        "/api/auth/login", json={"email": "test-admin@ges-g50.com", "password": "InitialPassw0rd!"}
    )
    assert locked_response.status_code == 423
