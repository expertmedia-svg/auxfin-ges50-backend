"""Surveillance d'un dossier local. Dans cette version, le scan est reel mais
declenche a la demande (bouton "verifier maintenant" ou tache planifiee),
plutot qu'un demon qui tournerait en permanence — l'architecture (interface
EvidenceIngestionAdapter) permet d'ajouter un scan continu plus tard sans
changer le moteur d'ingestion."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.services.ingestion.base import EvidenceIngestionAdapter, IngestedFile

settings = get_settings()
MEDIA_EXTENSIONS = settings.allowed_image_extensions | settings.allowed_video_extensions


class FolderWatchAdapter(EvidenceIngestionAdapter):
    source_code = "folder_watch"

    def collect(self, folder_path: str, already_seen_paths: set[str] | None = None, **kwargs) -> list[IngestedFile]:
        already_seen_paths = already_seen_paths or set()
        folder = Path(folder_path)
        if not folder.is_dir():
            raise NotADirectoryError(f"Dossier introuvable: {folder_path}")

        results: list[IngestedFile] = []
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            if str(path) in already_seen_paths:
                continue
            results.append(IngestedFile(source_path=path, original_filename=path.name))
        return results
