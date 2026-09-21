"""Reference images from existing evidence, never a fabricated diagnosis."""
import base64
from pathlib import Path

from app.services.storage.storage_service import get_storage_service


def reference_images(entries):
    images = []
    size = 0
    for task, ev in entries:
        frames = sorted(ev.frames, key=lambda f: (f.is_selected_best, f.position == "end"), reverse=True)
        stored = frames[0].storage_path if frames else ev.storage_path if ev.media_type == "image" else None
        if not stored:
            continue
        path = get_storage_service().resolve(stored)
        suffix = Path(path).suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png") or not Path(path).is_file():
            continue
        length = Path(path).stat().st_size
        if length > 2_000_000 or size + length > 10_000_000:
            continue
        size += length
        images.append({"data": base64.b64encode(Path(path).read_bytes()).decode(),
                       "mimetype": "image/png" if suffix == ".png" else "image/jpeg",
                       "caption": (f"Référence {task.id} — {ev.original_filename}. "
                                   "Image de repérage, pas nécessairement l'instant du problème. "
                                   f"Motif : {task.reason}")[:1000]})
    return images
