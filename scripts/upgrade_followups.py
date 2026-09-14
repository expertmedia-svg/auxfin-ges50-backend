"""Sauvegarde SQLite, migration additive et reprise des dossiers, sans envoi de messages."""
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.database import SessionLocal, engine
from app.models.evidence import EvidenceFile
from app.models.followup import EvidenceFollowup
from app.services.followups import update_followups


def main():
    if engine.url.get_backend_name() == "sqlite":
        path = Path(engine.url.database)
        backup = path.with_name(f"{path.stem}_before_followups_{datetime.now():%Y%m%d_%H%M%S}.db")
        with sqlite3.connect(str(path)) as source, sqlite3.connect(str(backup)) as destination:
            source.backup(destination)
        print(f"Sauvegarde : {backup.name}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    with SessionLocal() as db:
        for evidence in db.query(EvidenceFile).filter(EvidenceFile.processing_status.notin_(["PENDING", "QUEUED", "PROCESSING"])):
            update_followups(db, evidence)
            db.flush()
        for evidence in db.query(EvidenceFile).filter_by(processing_status="COMPLETED"):
            update_followups(db, evidence)
        db.commit()
        print(f"Dossiers de suivi : {db.query(EvidenceFollowup).count()}. Aucun message envoyé.")


if __name__ == "__main__":
    main()
