"""Interface commune d'ingestion de preuves (section 6.C). Chaque source
(upload manuel, export WhatsApp, surveillance de dossier, futur connecteur
WhatsApp autorise) implemente cette interface sans que le moteur de traitement
(OCR/rapprochement) n'ait a connaitre l'origine du fichier."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class IngestedFile:
    source_path: Path
    original_filename: str
    sender_name: str | None = None
    sender_phone: str | None = None
    whatsapp_message_date: datetime | None = None


class EvidenceIngestionAdapter(ABC):
    """Contrat que doit respecter toute source d'ingestion de preuves."""

    source_code: str

    @abstractmethod
    def collect(self, **kwargs) -> list[IngestedFile]:
        """Retourne la liste des fichiers a ingerer, avec leurs metadonnees connues."""
