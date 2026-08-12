"""Regression du bug critique trouve en Phase B : quand Redis/Celery est
injoignable, l'enqueue d'une tache de traitement pouvait bloquer la reponse
HTTP de /evidence/upload pendant plus de 2 HEURES (retry/backoff kombu par
defaut), rendant l'API totalement indisponible des qu'un worker n'etait pas
demarre. `app/api/routers/evidence._enqueue_processing` doit desormais
toujours revenir en quelques secondes, quoi qu'il arrive cote broker."""

from __future__ import annotations

import time

from app.api.routers.evidence import _ENQUEUE_TIMEOUT_SECONDS, _enqueue_processing


def test_enqueue_processing_returns_quickly_when_broker_hangs(monkeypatch):
    def _hanging_delay(evidence_id: str):
        time.sleep(60)  # simule un broker qui ne repond jamais

    import app.workers.tasks as tasks_module

    monkeypatch.setattr(tasks_module.process_evidence_task, "delay", _hanging_delay)

    started = time.monotonic()
    _enqueue_processing("some-evidence-id")
    elapsed = time.monotonic() - started

    assert elapsed < _ENQUEUE_TIMEOUT_SECONDS + 2, (
        f"_enqueue_processing a bloque {elapsed:.1f}s : le garde-fou de timeout n'a pas fonctionne"
    )


def test_enqueue_processing_returns_quickly_when_broker_raises(monkeypatch):
    def _raising_delay(evidence_id: str):
        raise ConnectionError("broker injoignable")

    import app.workers.tasks as tasks_module

    monkeypatch.setattr(tasks_module.process_evidence_task, "delay", _raising_delay)

    started = time.monotonic()
    _enqueue_processing("some-evidence-id")
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
