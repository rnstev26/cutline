"""Read every property that a handoff can silently change.

Duration, frame count, stream count and codec are NOT sufficient: measured, a
rotated source passed through an ffmpeg filter graph loses its rotation side
data while all four of those stay identical. Geometry, SAR, rotation, audio
parameters and per-stream start_time are all part of the set for that reason.

One property is not merely READ here, it is MEASURED when the container omits
it: see `_count_video_packets`. A missing `nb_frames` used to leave `None` in a
quantity the cut boundary compares directionally, and a comparison against
`None` fails closed -- correctly, but on a question nobody should have had to
ask. Removing the unknown is the fix; exempting it would not have been.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
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

    # §4.1's property table names "stream count + kinds -- catches a dropped
    # audio track", and until now nothing in the model could express it: every
    # other property is addressed as `video.*` or `audio.*`, SINGULAR, and
    # `.video` / `.audio` above resolve first-of-kind. A source with two audio
    # tracks that lost one across a handoff therefore matched on every named
    # property of the FIRST audio stream and the boundary reported OK.
    #
    # Measured 2026-08-23, which is why these two are counted and a general
    # ordered-kinds tuple is not:
    #   * auto-editor 31.5.0 PRESERVES audio streams -- 1 -> 1 and 2 -> 2.
    #   * it DROPS `data` streams -- a real Apple-written .MOV carrying
    #     (audio, video, data, data) rendered as (video, audio).
    # So audio and video counts can be invariant at the cut boundary and an
    # ordered all-kinds tuple could not be. Non-a/v streams are outside v1's
    # model by that measurement, not by oversight.
    @property
    def video_streams(self) -> int:
        return sum(1 for s in self.streams if s.kind == "video")

    @property
    def audio_streams(self) -> int:
        return sum(1 for s in self.streams if s.kind == "audio")


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


def _count_video_packets(ffprobe: Path, path: Path) -> int | None:
    """Count the FIRST video stream's coded frames by demuxing, not decoding.

    Some containers carry no per-stream frame count in their header, and it is
    not an exotic case: measured on this machine, a fragmented `.mov`
    (`-movflags +frag_keyframe+empty_moov`, what a crash-safe recorder writes)
    and a Matroska remux of the same content both report `nb_frames=N/A` for
    every stream, while a normally-muxed `.mov` reports it. `flow.cut()`
    compares that number directionally, so an absent one made a healthy
    recording unverifiable.

    WHY PACKETS AND NOT FRAMES. `-count_frames` decodes; `-count_packets` only
    demuxes, and for one coded video frame per packet the two agree. Measured
    on 2026-08-23, ffprobe 8.1.1, seven files spanning h264 / hevc / no-B-frames
    / real Apple-written VFR capture -- header `nb_frames`, `-count_packets`
    and `-count_frames` returned the SAME integer in 7 of 7 cases
    (tests/test_probe.py::test_packet_count_agrees_with_the_header_frame_count
    is the standing control, so a codec or ffmpeg that breaks the identity is
    caught rather than assumed away).

    And the cost difference is not marginal. On real 1080p footage (88.64 s,
    168 MB, 2659 frames):

        -show_streams alone     0.03 s
        -count_packets          0.05 s   <- ~0.5 s extrapolated to 12 minutes
        -count_frames          15.07 s   <- ~122 s extrapolated to 12 minutes

    Fails closed: anything unreadable returns None, exactly as before. A count
    we could not take is never evidence that the artifact is sound.
    """
    proc = subprocess.run(
        [
            str(ffprobe),
            "-v", "error",
            "-select_streams", "v:0",
            "-count_packets",
            "-show_entries", "stream=nb_read_packets",
            # JSON, not `-of csv=p=0`. Measured: on a stream carrying side data
            # (every rotated file this project has) the csv writer emits a
            # TRAILING COMMA -- "360," -- which parses as no integer at all, so
            # the count came back None on exactly the sources §2 is about, and
            # None is indistinguishable here from "the container omitted it".
            # tests/test_probe.py::test_packet_count_agrees_with_the_header_
            # frame_count caught this on its first run.
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        streams = json.loads(proc.stdout).get("streams") or []
    except json.JSONDecodeError:
        return None
    if not streams:
        return None
    return _as_int(streams[0].get("nb_read_packets"))


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

    # Only the FIRST video stream is recovered, because it is the only one the
    # property model addresses (`MediaInfo.video` is first-of-kind). Counting
    # every stream would pay for numbers nothing reads.
    first_video = next((i for i, s in enumerate(streams) if s.kind == "video"), None)
    if first_video is not None and streams[first_video].nb_frames is None:
        counted = _count_video_packets(ffprobe.path, path)
        if counted is not None:
            streams[first_video] = replace(streams[first_video], nb_frames=counted)

    return MediaInfo(
        path=path,
        duration=_as_float(data.get("format", {}).get("duration")),
        streams=tuple(streams),
        rotation=rotation,
    )
