from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.identity import User
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Limitation des tentatives de connexion (section 21 / Phase B point 8) :
# apres MAX_FAILED_ATTEMPTS echecs consecutifs, le compte est verrouille
# pendant LOCKOUT_MINUTES avant de pouvoir retenter.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _is_locked(user: User) -> bool:
    if not user.locked_until:
        return False
    return datetime.fromisoformat(user.locked_until) > datetime.now(UTC)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()

    if user is not None and _is_locked(user):
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Compte verrouille suite a trop de tentatives echouees. Reessayez apres "
            f"{user.locked_until}.",
        )

    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        if user is not None and user.is_active:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = (
                    datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)
                ).isoformat()
                record_audit(
                    db, user_id=user.id, action="auth.account_locked", entity_type="user", entity_id=user.id,
                    details={"failed_attempts": user.failed_login_attempts},
                )
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC).isoformat()
    record_audit(
        db,
        user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    role_codes = user.role_codes
    access_token = create_access_token(user.id, {"roles": role_codes, "email": user.email})
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        decoded = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = db.get(User, decoded["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utilisateur introuvable ou desactive")

    access_token = create_access_token(user.id, {"roles": user.role_codes, "email": user.email})
    new_refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    record_audit(
        db,
        user_id=user.id,
        action="auth.logout",
        entity_type="user",
        entity_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=user.role_codes,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe actuel incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Le nouveau mot de passe doit differer de l'ancien")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    record_audit(db, user_id=user.id, action="auth.change_password", entity_type="user", entity_id=user.id)
    db.commit()
