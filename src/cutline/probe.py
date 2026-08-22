"""Read every property that a handoff can silently change.

Duration, frame count, stream count and codec are NOT sufficient: measured, a
rotated source passed through an ffmpeg filter graph loses its rotation side
data while all four of those stay identical. Geometry, SAR, rotation, audio
parameters and per-stream start_time are all part of the set for that reason.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cutline.tools import ToolError, find_tool


@dataclass(frozen=True)
class StreamInfo:
    kind: str
    codec: str | None = None
    profile: str | None = None
    pix_fmt: str | None = None
    width: int | None = None
    height: int | None = None
    sar: str | None = None
    dar: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    start_time: float = 0.0
    nb_frames: int | None = None


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    streams: tuple[StreamInfo, ...]
    rotation: int | None

    @property
    def video(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.kind == "audio"), None)


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rotation_from(stream: dict) -> int | None:
    """Rotation lives in side_data_list, not in the stream's own fields.

    Returns None when absent — and absent is meaningfully different from zero,
    so this must never coerce to 0.
    """
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return _as_int(side["rotation"])
    return None


def probe(path: Path) -> MediaInfo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"cannot probe a file that does not exist: {path}")
    ffprobe = find_tool("ffprobe")
    proc = subprocess.run(
        [
            str(ffprobe.path),
            "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise ToolError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)

    streams: list[StreamInfo] = []
    rotation: int | None = None
    for raw in data.get("streams", []):
        kind = raw.get("codec_type", "unknown")
        if kind == "video" and rotation is None:
            rotation = _rotation_from(raw)
        streams.append(
            StreamInfo(
                kind=kind,
                codec=raw.get("codec_name"),
                profile=raw.get("profile"),
                pix_fmt=raw.get("pix_fmt"),
                width=_as_int(raw.get("width")),
                height=_as_int(raw.get("height")),
                sar=raw.get("sample_aspect_ratio"),
                dar=raw.get("display_aspect_ratio"),
                sample_rate=_as_int(raw.get("sample_rate")),
                channels=_as_int(raw.get("channels")),
                start_time=_as_float(raw.get("start_time")),
                nb_frames=_as_int(raw.get("nb_frames")),
            )
        )

    return MediaInfo(
        path=path,
        duration=_as_float(data.get("format", {}).get("duration")),
        streams=tuple(streams),
        rotation=rotation,
    )
