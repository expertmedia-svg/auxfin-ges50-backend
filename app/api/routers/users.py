from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.models.identity import Role, User, UserRole
from app.schemas.users import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active, roles=user.role_codes
    )


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_roles(RoleCode.SUPER_ADMIN, RoleCode.ADMIN))
) -> list[UserOut]:
    return [_to_out(u) for u in db.query(User).order_by(User.full_name).all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(RoleCode.SUPER_ADMIN, RoleCode.ADMIN)),
) -> UserOut:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Un utilisateur avec cet email existe deja")

    user = User(email=email, full_name=payload.full_name, hashed_password=hash_password(payload.password))
    db.add(user)
    db.flush()

    for code in payload.role_codes:
        role = db.query(Role).filter(Role.code == code).one_or_none()
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Role inconnu: {code}")
        db.add(UserRole(user_id=user.id, role_id=role.id))

    record_audit(db, user_id=actor.id, action="user.create", entity_type="user", entity_id=user.id)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles(RoleCode.SUPER_ADMIN, RoleCode.ADMIN)),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.role_codes is not None:
        db.query(UserRole).filter(UserRole.user_id == user.id).delete()
        for code in payload.role_codes:
            role = db.query(Role).filter(Role.code == code).one_or_none()
            if role is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Role inconnu: {code}")
            db.add(UserRole(user_id=user.id, role_id=role.id))

    record_audit(db, user_id=actor.id, action="user.update", entity_type="user", entity_id=user.id)
    db.commit()
    db.refresh(user)
    return _to_out(user)
