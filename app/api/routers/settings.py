from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.permissions import ADMIN_ROLES, READ_ROLES
from app.models.identity import User
from app.models.system import SystemSetting
from app.schemas.settings import SettingItem, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_SETTINGS: dict[str, dict] = {
    "ocr_confidence_threshold": {"value": 0.55, "description": "Seuil de confiance OCR minimal"},
    "fuzzy_match_threshold": {"value": 88, "description": "Seuil de correspondance floue des IDs (0-100)"},
    "reconciliation_date_tolerance_days": {"value": 0, "description": "Tolerance de date pour le rapprochement (jours)"},
    "max_upload_size_mb": {"value": 200, "description": "Taille maximale des fichiers importes (Mo)"},
    "retention_days": {"value": 365, "description": "Duree de conservation des preuves (jours)"},
    "allowed_extensions": {
        "value": [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".zip"],
        "description": "Extensions de fichiers autorisees pour l'import de preuves",
    },
}


def ensure_default_settings(db: Session) -> None:
    existing_keys = {s.key for s in db.query(SystemSetting.key).all()}
    for key, config in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            db.add(SystemSetting(key=key, value=config["value"], description=config["description"]))
    db.commit()


@router.get("", response_model=list[SettingItem])
def get_settings_list(
    db: Session = Depends(get_db), _: User = Depends(require_roles(*READ_ROLES))
) -> list[SettingItem]:
    ensure_default_settings(db)
    return [SettingItem(key=s.key, value=s.value, description=s.description) for s in db.query(SystemSetting).all()]


@router.patch("", response_model=list[SettingItem])
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN_ROLES)),
) -> list[SettingItem]:
    ensure_default_settings(db)
    for key, value in payload.values.items():
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).one_or_none()
        if setting is None:
            setting = SystemSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value
    record_audit(db, user_id=user.id, action="settings.update", details={"keys": list(payload.values.keys())})
    db.commit()
    return [SettingItem(key=s.key, value=s.value, description=s.description) for s in db.query(SystemSetting).all()]
