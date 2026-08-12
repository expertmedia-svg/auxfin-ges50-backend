import pytest
from fastapi import HTTPException

from app.core.deps import require_roles
from app.core.permissions import RoleCode
from app.core.security import TokenError, create_access_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("Sup3rSecret!")
    assert verify_password("Sup3rSecret!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token("user-123", {"roles": ["admin"]})
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-123"
    assert payload["roles"] == ["admin"]


def test_decode_token_wrong_type_raises():
    token = create_access_token("user-123")
    with pytest.raises(TokenError):
        decode_token(token, expected_type="refresh")


class _FakeUser:
    def __init__(self, roles):
        self.role_codes = roles


def test_require_roles_allows_matching_role():
    dependency = require_roles(RoleCode.ADMIN, RoleCode.SUPER_ADMIN)
    user = _FakeUser([RoleCode.ADMIN.value])
    assert dependency(user) is user


def test_require_roles_rejects_missing_role():
    dependency = require_roles(RoleCode.ADMIN)
    user = _FakeUser([RoleCode.LECTEUR.value])
    with pytest.raises(HTTPException) as excinfo:
        dependency(user)
    assert excinfo.value.status_code == 403
