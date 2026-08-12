"""Tests de concurrence reels (Phase B, point 2) : plusieurs connexions
ecrivent simultanement dans PostgreSQL pour verifier l'absence de
deadlock/corruption et l'unicite des contraintes sous charge concurrente.
Ignores automatiquement si la suite tourne sur SQLite (TEST_DATABASE_URL
non defini) : la concurrence multi-connexions n'a pas de sens la-bas."""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.applications import Application

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL.startswith("sqlite"),
    reason="Test de concurrence multi-connexions reserve a PostgreSQL (TEST_DATABASE_URL)",
)


@pytest.fixture()
def pg_engine():
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


def test_concurrent_inserts_all_committed(pg_engine):
    """20 threads inserent chacun une application distincte en parallele :
    toutes les lignes doivent etre visibles apres coup, sans deadlock."""
    Session = sessionmaker(bind=pg_engine)
    codes = [f"concurrency-test-{uuid.uuid4().hex[:8]}" for _ in range(20)]
    errors: list[Exception] = []

    def _insert(code: str) -> None:
        session = Session()
        try:
            session.add(Application(code=code, name=f"App {code}"))
            session.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_insert, args=(c,)) for c in codes]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Erreurs pendant les insertions concurrentes: {errors}"

    verify_session = Session()
    try:
        found = verify_session.query(Application).filter(Application.code.in_(codes)).count()
        assert found == len(codes)
    finally:
        for code in codes:
            verify_session.query(Application).filter(Application.code == code).delete()
        verify_session.commit()
        verify_session.close()


def test_concurrent_duplicate_code_violates_unique_constraint(pg_engine):
    """Deux connexions tentent de creer la meme application (meme code
    unique) en meme temps : une seule doit reussir, l'autre doit echouer
    proprement sur la contrainte d'unicite (pas de corruption silencieuse)."""
    Session = sessionmaker(bind=pg_engine)
    shared_code = f"race-{uuid.uuid4().hex[:8]}"
    results: list[str] = []
    lock = threading.Barrier(2, timeout=10)

    def _insert() -> None:
        session = Session()
        try:
            lock.wait()
            session.add(Application(code=shared_code, name="Race"))
            session.commit()
            results.append("ok")
        except IntegrityError:
            session.rollback()
            results.append("conflict")
        except Exception:  # noqa: BLE001
            session.rollback()
            results.append("other_error")
        finally:
            session.close()

    threads = [threading.Thread(target=_insert) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results.count("ok") == 1, f"Une seule insertion aurait du reussir, resultats: {results}"
    assert results.count("conflict") == 1, f"L'autre aurait du echouer sur la contrainte unique: {results}"

    cleanup = Session()
    try:
        cleanup.query(Application).filter(Application.code == shared_code).delete()
        cleanup.commit()
    finally:
        cleanup.close()
