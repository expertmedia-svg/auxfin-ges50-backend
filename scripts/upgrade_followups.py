"""Sauvegarde SQLite, migration additive et reprise des dossiers, sans envoi de messages."""
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.database import SessionLocal, engine
from app.models.followup import EvidenceFollowup
from app.services.followup_rebuild import rebuild_followups


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
        print("Reprise groupée des dossiers…", flush=True)
        rebuild_followups(db, lambda done, total: print(f"{done}/{total} preuves examinées", flush=True))
        db.commit()
        print(f"Dossiers de suivi : {db.query(EvidenceFollowup).count()}. Aucun message envoyé.")


if __name__ == "__main__":
    main()
