from celery import Celery

from app.core.config import get_settings

settings = get_settings()
_is_filesystem_broker = settings.celery_broker_url.startswith("filesystem://")

if _is_filesystem_broker:
    # Alternative sans Docker ni Redis (Phase C, decision explicite : pas de
    # Docker). Kombu ecrit/lit les messages comme de simples fichiers sur
    # disque — suffisant pour le volume vise (~1000 preuves/semaine) et
    # reellement teste (worker --pool=solo sous Windows natif). Redis natif
    # (apt install redis-server, sans Docker) reste recommande en production
    # Linux pour de meilleures performances sous forte charge.
    settings.ensure_celery_filesystem_dirs()
    _result_backend = None  # aucun resultat de tache n'est jamais attendu (fire-and-forget)
else:
    _result_backend = settings.celery_result_backend

celery_app = Celery(
    "ges_g50_sync_control",
    broker=settings.celery_broker_url,
    backend=_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_ignore_result=_is_filesystem_broker,
    # Sans ces trois reglages, un appel a .delay() quand le broker est
    # injoignable peut bloquer PLUSIEURS DIZAINES DE MINUTES avant
    # d'echouer (retry/backoff par defaut de kombu quasi illimite) —
    # bug reel trouve en testant /evidence/upload sans worker demarre
    # (la requete HTTP restait bloquee ~2h). broker_connection_retry=False
    # fait echouer .delay() rapidement (broker_connection_timeout secondes)
    # au lieu de reessayer indefiniment, pour que le try/except appelant
    # (app.api.routers.evidence._enqueue_processing) reprenne la main vite.
    broker_connection_retry=False,
    broker_connection_retry_on_startup=False,
    broker_connection_timeout=3,
)

if _is_filesystem_broker:
    broker_dir = settings.celery_filesystem_broker_dir
    celery_app.conf.broker_transport_options = {
        "data_folder_in": str(broker_dir / "out"),
        "data_folder_out": str(broker_dir / "out"),
        "data_folder_processed": str(broker_dir / "processed"),
    }
else:
    celery_app.conf.broker_transport_options = {"max_retries": 1}
