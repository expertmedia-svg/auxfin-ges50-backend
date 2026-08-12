from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import ADMIN_ROLES, READ_ROLES
from app.models.applications import Application, ApplicationProfile
from app.models.identity import User
from app.schemas.applications import ApplicationCreate, ApplicationOut, ApplicationUpdate

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[Application]:
    return (
        db.query(Application)
        .options(joinedload(Application.profile))
        .order_by(Application.name)
        .all()
    )


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> Application:
    if db.query(Application).filter(Application.code == payload.code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce code d'application existe deja")

    application = Application(code=payload.code, name=payload.name, is_active=payload.is_active)
    db.add(application)
    db.flush()

    profile = ApplicationProfile(application_id=application.id, **payload.profile.model_dump())
    db.add(profile)

    record_audit(
        db, user_id=user.id, action="application.create", entity_type="application", entity_id=application.id
    )
    db.commit()
    db.refresh(application)
    return application


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application introuvable")

    if payload.name is not None:
        application.name = payload.name
    if payload.is_active is not None:
        application.is_active = payload.is_active
    if payload.profile is not None:
        if application.profile is None:
            application.profile = ApplicationProfile(application_id=application.id)
        for field, value in payload.profile.model_dump().items():
            setattr(application.profile, field, value)

    record_audit(
        db, user_id=user.id, action="application.update", entity_type="application", entity_id=application.id
    )
    db.commit()
    db.refresh(application)
    return application


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_application(
    application_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> None:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application introuvable")
    application.is_active = False
    record_audit(
        db, user_id=user.id, action="application.deactivate", entity_type="application", entity_id=application.id
    )
    db.commit()
