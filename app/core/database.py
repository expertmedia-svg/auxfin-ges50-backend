from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_database_url = settings.resolved_database_url
_is_sqlite = _database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(_database_url, connect_args=connect_args, future=True)

if _is_sqlite:
    # Ecoute sur CETTE instance de moteur uniquement (et non sur la classe
    # Engine globale) : un listener global s'appliquerait aussi aux moteurs
    # PostgreSQL crees ailleurs dans le process (ex: tests/conftest.py en
    # Phase B), ou "PRAGMA" provoque une erreur de syntaxe SQL.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
