from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    return _create_token(
        subject, timedelta(minutes=settings.access_token_expire_minutes), "access", extra_claims
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject, timedelta(minutes=settings.refresh_token_expire_minutes), "refresh", None
    )


def _create_token(
    subject: str, expires_delta: timedelta, token_type: str, extra_claims: dict[str, Any] | None
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    pass


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Le token a expire") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token invalide") from exc
    if payload.get("type") != expected_type:
        raise TokenError("Type de token invalide")
    return payload
