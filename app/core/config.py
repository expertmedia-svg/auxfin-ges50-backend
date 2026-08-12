from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), extra="ignore")

    app_name: str = "GES G50 - Controle des synchronisations"
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    refresh_token_expire_minutes: int = 60 * 24 * 14

    database_url: str | None = None

    # Par defaut : Redis natif (production Linux/OVH, `apt install redis-server`,
    # sans Docker). Sur un poste de developpement Windows sans Docker ni WSL2
    # fonctionnel, definir CELERY_BROKER_URL=filesystem:// dans .env pour
    # utiliser le transport fichier de Kombu (aucun service externe requis,
    # valide reellement en Phase C — voir README section "Sans Docker").
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Racine de stockage : les sous-dossiers (uploads/frames/reports) et le
    # fichier SQLite par defaut en derivent, pour qu'une seule variable
    # d'environnement (STORAGE_ROOT) suffise a relocaliser tout le stockage.
    storage_root: Path = PROJECT_ROOT / "storage"

    max_upload_size_mb: int = 200
    allowed_image_extensions: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    allowed_video_extensions: set[str] = {".mp4", ".mov", ".avi", ".mkv", ".3gp"}
    allowed_archive_extensions: set[str] = {".zip"}
    allowed_export_extensions: set[str] = {".xlsx", ".xls", ".csv"}

    ocr_confidence_threshold: float = 0.55
    fuzzy_match_threshold: int = 88
    reconciliation_date_tolerance_days: int = 0

    # 5 frames pres du debut (pour l'ID/date) et 5 pres de la fin (pour le
    # statut de synchronisation), pour alleger l'analyse. Le "10" a ete
    # retire des offsets de fin (le moins susceptible de montrer l'ecran de
    # confirmation final) plutot que "1" (le plus proche de la toute fin).
    video_start_offsets_seconds: list[float] = [0, 0.5, 1, 2, 3]
    video_end_offsets_seconds: list[float] = [8, 6, 4, 2, 1]

    cors_allow_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    initial_admin_email: str = "admin@ges-g50.com"
    # Pas de valeur par defaut : un mot de passe faible en dur ne doit
    # jamais se retrouver en production (Phase B, section 8). Si non
    # fourni, scripts/create_admin.py genere un mot de passe aleatoire
    # fort, affiche une seule fois, avec changement obligatoire a la
    # premiere connexion (User.must_change_password).
    initial_admin_password: str | None = None
    initial_admin_full_name: str = "Administrateur GES G50"

    tesseract_cmd: str | None = None
    ffmpeg_cmd: str = "ffmpeg"
    ffprobe_cmd: str = "ffprobe"

    # Passerelle WhatsApp (service Node whatsapp-gateway, Phase C). Le jeton
    # n'a pas de valeur par defaut faible (meme regle que SECRET_KEY /
    # INITIAL_ADMIN_PASSWORD) : sans lui, les webhooks /whatsapp/webhook/*
    # refusent toute requete.
    whatsapp_gateway_url: str = "http://127.0.0.1:4001"
    whatsapp_gateway_shared_secret: str | None = None

    @property
    def upload_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def frames_dir(self) -> Path:
        return self.storage_root / "frames"

    @property
    def reports_dir(self) -> Path:
        return self.storage_root / "reports"

    @property
    def celery_filesystem_broker_dir(self) -> Path:
        return self.storage_root / "celery_broker"

    @property
    def whatsapp_session_dir(self) -> Path:
        return self.storage_root / "whatsapp_session"

    @property
    def whatsapp_inbox_dir(self) -> Path:
        return self.storage_root / "whatsapp_inbox"

    def ensure_celery_filesystem_dirs(self) -> None:
        for sub in ("in", "out", "processed"):
            (self.celery_filesystem_broker_dir / sub).mkdir(parents=True, exist_ok=True)

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.storage_root / 'ges_g50.db'}"

    def ensure_directories(self) -> None:
        for path in (
            self.storage_root,
            self.upload_dir,
            self.frames_dir,
            self.reports_dir,
            self.whatsapp_session_dir,
            self.whatsapp_inbox_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


DEFAULT_SECRET_KEY = "change-me-in-production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    if settings.environment == "production" and settings.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY par defaut detectee avec ENVIRONMENT=production. "
            "Definissez une SECRET_KEY forte et unique dans .env avant de demarrer en production."
        )
    return settings
