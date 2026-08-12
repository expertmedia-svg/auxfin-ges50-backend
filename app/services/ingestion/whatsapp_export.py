"""Import d'un export de discussion WhatsApp (.txt + medias, ou zip contenant
les deux). Extrait, quand disponible, la date/heure du message, l'expediteur
et le nom du media associe (section 6.B)."""

from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.services.ingestion.base import EvidenceIngestionAdapter, IngestedFile

settings = get_settings()
MEDIA_EXTENSIONS = settings.allowed_image_extensions | settings.allowed_video_extensions

# Formats geres :
#   Android : "30/07/2026, 10:28 - Jean Ouedraogo: message"
#   iOS     : "[30/07/2026, 10:28:03] Jean Ouedraogo: message"
_ANDROID_LINE_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*"
    r"(?P<sender>[^:]+):\s*(?P<message>.*)$"
)
_IOS_LINE_RE = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s*"
    r"(?P<sender>[^:]+):\s*(?P<message>.*)$"
)
_ATTACHMENT_MARKERS = ("joint", "omitted", "omis", "<attached:", "piece jointe", "pièce jointe")
_FILENAME_RE = re.compile(r"([\w\-]+\.(?:jpg|jpeg|png|mp4|mov|webp|3gp|avi))", re.IGNORECASE)


@dataclass
class WhatsAppMessage:
    timestamp: datetime | None
    sender: str
    raw_text: str
    media_filename: str | None


def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
    for day_first in (True, False):
        for fmt_date in ("%d/%m/%Y", "%d/%m/%y") if day_first else ("%m/%d/%Y", "%m/%d/%y"):
            for fmt_time in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(f"{date_str} {time_str}", f"{fmt_date} {fmt_time}")
                except ValueError:
                    continue
    return None


def parse_whatsapp_export(txt_path: str | Path) -> list[WhatsAppMessage]:
    messages: list[WhatsAppMessage] = []
    text = Path(txt_path).read_text(encoding="utf-8", errors="ignore")

    for raw_line in text.splitlines():
        line = raw_line.replace("‎", "").replace("‏", "").strip()
        if not line:
            continue
        match = _ANDROID_LINE_RE.match(line) or _IOS_LINE_RE.match(line)
        if not match:
            continue

        timestamp = _parse_datetime(match.group("date"), match.group("time"))
        message_text = match.group("message").strip()
        media_filename = None

        filename_match = _FILENAME_RE.search(message_text)
        if filename_match:
            media_filename = filename_match.group(1)
        elif any(marker in message_text.lower() for marker in _ATTACHMENT_MARKERS):
            media_filename = "__unnamed_attachment__"

        messages.append(
            WhatsAppMessage(
                timestamp=timestamp,
                sender=match.group("sender").strip(),
                raw_text=message_text,
                media_filename=media_filename,
            )
        )
    return messages


class WhatsAppExportAdapter(EvidenceIngestionAdapter):
    source_code = "whatsapp_export"

    def collect(
        self, txt_path: str | None = None, media_dir: str | None = None, zip_path: str | None = None, **kwargs
    ) -> list[IngestedFile]:
        work_dir: Path
        if zip_path:
            work_dir = Path(tempfile.mkdtemp(prefix="ges_g50_wa_export_"))
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(work_dir)
            txt_candidates = list(work_dir.glob("*.txt")) + list(work_dir.rglob("*.txt"))
            if not txt_candidates:
                raise ValueError("Aucun fichier .txt de discussion trouve dans l'archive")
            txt_file = txt_candidates[0]
            media_root = work_dir
        else:
            if not txt_path:
                raise ValueError("txt_path ou zip_path requis")
            txt_file = Path(txt_path)
            media_root = Path(media_dir) if media_dir else txt_file.parent

        messages = parse_whatsapp_export(txt_file)
        media_files_by_name = {p.name: p for p in media_root.rglob("*") if p.suffix.lower() in MEDIA_EXTENSIONS}

        results: list[IngestedFile] = []
        unnamed_pool = sorted(
            (p for p in media_files_by_name.values() if p.name not in [m.media_filename for m in messages]),
            key=lambda p: p.name,
        )

        for message in messages:
            if not message.media_filename:
                continue
            resolved_path: Path | None = None
            if message.media_filename in media_files_by_name:
                resolved_path = media_files_by_name[message.media_filename]
            elif message.media_filename == "__unnamed_attachment__" and unnamed_pool:
                resolved_path = unnamed_pool.pop(0)

            if resolved_path is None:
                continue

            results.append(
                IngestedFile(
                    source_path=resolved_path,
                    original_filename=resolved_path.name,
                    sender_name=message.sender,
                    whatsapp_message_date=message.timestamp,
                )
            )
        return results
