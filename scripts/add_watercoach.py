"""Ajout idempotent de WaterCoach, sans modifier les autres profils."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.applications import Application, ApplicationProfile
from scripts.seed_config import APPLICATION_PROFILES


def add_watercoach(db):
    data = next(p for p in APPLICATION_PROFILES if p["code"] == "watercoach")
    application = db.query(Application).filter(Application.code == "watercoach").one_or_none()
    if application is None:
        application = Application(code="watercoach", name="WaterCoach")
        db.add(application)
        db.flush()
    profile = db.query(ApplicationProfile).filter(ApplicationProfile.application_id == application.id).one_or_none()
    if profile is None:
        db.add(ApplicationProfile(application_id=application.id,
            **{k: v for k, v in data.items() if k not in ("code", "name")}))
    db.commit()
    return application.id


if __name__ == "__main__":
    with SessionLocal() as db:
        print("WaterCoach disponible :", add_watercoach(db))
