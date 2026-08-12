from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from app.core.config import get_settings
from app.services.ingestion.base import EvidenceIngestionAdapter, IngestedFile

settings = get_settings()

ALL_ALLOWED_EXTENSIONS = (
    settings.allowed_image_extensions
    | settings.allowed_video_extensions
    | settings.allowed_archive_extensions
)


class UnsupportedFileError(Exception):
    pass


class ManualUploadAdapter(EvidenceIngestionAdapter):
    """Import manuel : selection multiple, glisser-deposer, dossier, ou archive ZIP.
    Les fichiers sont deja enregistres temporairement par la route API ; cet
    adaptateur se charge de la validation et, le cas echeant, de l'extraction ZIP."""

    source_code = "manual_upload"

    def collect(self, file_paths: list[str], **kwargs) -> list[IngestedFile]:
        results: list[IngestedFile] = []
        for path_str in file_paths:
            path = Path(path_str)
            extension = path.suffix.lower()

            if extension not in ALL_ALLOWED_EXTENSIONS:
                raise UnsupportedFileError(f"Extension non autorisee: {extension} ({path.name})")

            if extension in settings.allowed_archive_extensions:
                results.extend(self._extract_zip(path))
            else:
                results.append(IngestedFile(source_path=path, original_filename=path.name))
        return results

    def _extract_zip(self, zip_path: Path) -> list[IngestedFile]:
        extracted: list[IngestedFile] = []
        extract_dir = Path(tempfile.mkdtemp(prefix="ges_g50_zip_"))
        media_extensions = settings.allowed_image_extensions | settings.allowed_video_extensions

        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                member_path = Path(member)
                if member_path.suffix.lower() not in media_extensions:
                    continue
                if member.startswith("/") or ".." in member_path.parts:
                    continue  # protection contre les chemins malicieux (zip slip)
                archive.extract(member, extract_dir)
                extracted.append(
                    IngestedFile(source_path=extract_dir / member, original_filename=member_path.name)
                )
        return extracted
