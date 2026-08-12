"""Abstraction de stockage des fichiers. Implementation disque local pour cette
version ; l'interface est concue pour accueillir plus tard un backend S3/MinIO
sans modifier les appelants (section 18)."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class StorageService(ABC):
    @abstractmethod
    def save(self, source_path: str | Path, subdirectory: str, suggested_name: str | None = None) -> str:
        """Copie/deplace un fichier vers le stockage et retourne son chemin logique (storage_path)."""

    @abstractmethod
    def resolve(self, storage_path: str) -> Path:
        """Retourne le chemin filesystem absolu correspondant a un storage_path."""

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        ...


def sha256_of_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class LocalDiskStorage(StorageService):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, source_path: str | Path, subdirectory: str, suggested_name: str | None = None) -> str:
        source_path = Path(source_path)
        target_dir = self.root / subdirectory
        target_dir.mkdir(parents=True, exist_ok=True)

        extension = source_path.suffix
        filename = suggested_name or f"{uuid.uuid4().hex}{extension}"
        target_path = target_dir / filename

        if source_path.resolve() != target_path.resolve():
            shutil.copy2(source_path, target_path)

        return str(Path(subdirectory) / filename)

    def resolve(self, storage_path: str) -> Path:
        return self.root / storage_path

    def delete(self, storage_path: str) -> None:
        path = self.resolve(storage_path)
        if path.exists():
            path.unlink()


_instance: LocalDiskStorage | None = None


def get_storage_service() -> LocalDiskStorage:
    global _instance
    if _instance is None:
        from app.core.config import get_settings

        _instance = LocalDiskStorage(get_settings().storage_root)
    return _instance
