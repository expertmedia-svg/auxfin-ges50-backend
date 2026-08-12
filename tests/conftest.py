import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  registers all models on Base.metadata
from app.core.database import Base

# TEST_DATABASE_URL permet de faire tourner exactement la meme suite de
# tests contre PostgreSQL reel plutot que SQLite en memoire (Phase B,
# validation de la compatibilite des requetes existantes). Exemple :
#   TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5434/ges_g50_test pytest tests/
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")

_engine_kwargs = {"connect_args": {"check_same_thread": False}} if _TEST_DATABASE_URL.startswith("sqlite") else {}
_engine = create_engine(_TEST_DATABASE_URL, **_engine_kwargs)
_is_postgres = not _TEST_DATABASE_URL.startswith("sqlite")

if _is_postgres:
    # Schema cree une seule fois pour la session de tests ; chaque test
    # tourne ensuite dans sa propre transaction annulee a la fin (isolation
    # rapide, sans recreer les tables a chaque test).
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)


@pytest.fixture()
def db_session():
    if _is_postgres:
        # Chaque test tourne dans une transaction externe annulee a la fin,
        # y compris quand le code applicatif appelle session.commit() (ce
        # qui termine normalement une transaction) : on relance un SAVEPOINT
        # a chaque fin de transaction pour que le rollback final englobe
        # toujours l'ensemble du test (recette standard SQLAlchemy).
        connection = _engine.connect()
        outer_transaction = connection.begin()
        TestingSessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
        session = TestingSessionLocal()
        session.begin_nested()

        @event.listens_for(session, "after_transaction_end")
        def _restart_savepoint(sess, trans):
            if trans.nested and not trans._parent.nested:
                sess.begin_nested()

        try:
            yield session
        finally:
            session.close()
            outer_transaction.rollback()
            connection.close()
    else:
        # StaticPool : un seul connection partagee par tous les checkouts,
        # indispensable pour sqlite ":memory:" des qu'un client HTTP de
        # test (FastAPI TestClient) peut checkout une connexion depuis un
        # autre contexte que celui qui a cree les tables (sinon chaque
        # nouvelle connexion pointe vers une base en memoire vide distincte).
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
