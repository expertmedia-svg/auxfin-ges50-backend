"""Extraction ciblee de quelques frames au debut et a la fin d'une video preuve,
via FFmpeg (binaire systeme). On n'analyse jamais la video entiere : seuls les
offsets configures (section 4 du cahier des charges) sont extraits.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


class VideoProbeError(Exception):
    pass


@dataclass
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int


@dataclass
class ExtractedFrame:
    position: str  # "start" | "end"
    offset_seconds: float
    path: str


def probe_video(video_path: str) -> VideoMetadata:
    cmd = [
        settings.ffprobe_cmd,
        "-v", "error",
        "-print_format", "json",
        "-show_entries", "format=duration:stream=width,height,codec_type",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise VideoProbeError(f"ffprobe a echoue: {proc.stderr.strip()}")

    data = json.loads(proc.stdout)
    duration = float(data.get("format", {}).get("duration", 0.0))
    width = height = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            break
    if duration <= 0:
        raise VideoProbeError("Duree de la video introuvable ou nulle")
    return VideoMetadata(duration_seconds=duration, width=width, height=height)


def _extract_single_frame(video_path: str, timestamp_seconds: float, output_path: str) -> bool:
    cmd = [
        settings.ffmpeg_cmd,
        "-y",
        "-ss", f"{max(timestamp_seconds, 0):.3f}",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return proc.returncode == 0 and Path(output_path).exists()


def extract_start_end_frames(
    video_path: str,
    output_dir: str,
    evidence_id: str,
    start_offsets: list[float] | None = None,
    end_offsets_from_end: list[float] | None = None,
) -> tuple[VideoMetadata, list[ExtractedFrame]]:
    """Extrait quelques frames pres du debut (offsets absolus depuis 0) et pres
    de la fin (offsets soustraits a la duree totale) d'une video, sans jamais
    decoder l'integralite du flux."""
    metadata = probe_video(video_path)
    start_offsets = start_offsets or settings.video_start_offsets_seconds
    end_offsets_from_end = end_offsets_from_end or settings.video_end_offsets_seconds

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[ExtractedFrame] = []

    for offset in start_offsets:
        if offset >= metadata.duration_seconds:
            continue
        output_path = str(out_dir / f"{evidence_id}_start_{offset}.jpg")
        if _extract_single_frame(video_path, offset, output_path):
            frames.append(ExtractedFrame(position="start", offset_seconds=offset, path=output_path))

    for offset_before_end in end_offsets_from_end:
        timestamp = metadata.duration_seconds - offset_before_end
        if timestamp < 0:
            continue
        output_path = str(out_dir / f"{evidence_id}_end_{offset_before_end}.jpg")
        if _extract_single_frame(video_path, timestamp, output_path):
            frames.append(
                ExtractedFrame(position="end", offset_seconds=offset_before_end, path=output_path)
            )

    if not frames:
        raise VideoProbeError("Aucune frame n'a pu etre extraite de la video")

    return metadata, frames
