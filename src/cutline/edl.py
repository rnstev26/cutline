"""Parse auto-editor's v3 and v1 timeline JSON into keep-segments.

Units are integer FRAMES at a rational timebase. Frame arithmetic is exact;
converting to float seconds first accumulates rounding error across hundreds of
cuts, so seconds are produced only for display.

v3 additionally carries resolution, samplerate and layout — a declared
expectation the rendered artifact can be verified against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

KEEP_SPEED = 1.0
CUT_SPEED = 99999.0


class EdlError(ValueError):
    """The EDL is malformed, or uses a feature outside v1 scope."""


@dataclass(frozen=True)
class Timebase:
    num: int
    den: int

    @classmethod
    def parse(cls, text: str) -> Timebase:
        try:
            num, den = text.split("/")
            tb = cls(int(num), int(den))
        except (ValueError, AttributeError) as exc:
            raise EdlError(f"unparseable timebase: {text!r}") from exc
        if tb.num <= 0 or tb.den <= 0:
            raise EdlError(f"non-positive timebase: {text!r}")
        return tb

    def to_seconds(self, frames: int) -> float:
        return frames * self.den / self.num


@dataclass(frozen=True)
class Keep:
    """One kept span. MEASURED semantics, not inferred ones.

    auto-editor 31.5.0, `--set-speed 2.0,0,1.5sec --export v3` on a 90-frame
    source produced two clips: `{start: 0, dur: 23, offset: 0, effects:
    ["speed:2.0"]}` then `{start: 23, dur: 45, offset: 45}`. Reading off that:
    `start` indexes the OUTPUT timeline, `offset` indexes the SOURCE, and `dur`
    is a length in OUTPUT frames (23 output frames for the 45 source frames the
    2.0 speed consumed). With no effect the two lengths coincide, which is why
    v1 can treat `dur` as both -- and why `_refuse_out_of_scope_effects` refuses
    the case where they diverge instead of quietly picking one reading.
    """

    start: int   # position in the OUTPUT timeline, frames
    dur: int     # length in OUTPUT frames (== source frames at unit speed)
    offset: int  # position in the SOURCE, frames

    @property
    def end(self) -> int:
        return self.start + self.dur


@dataclass(frozen=True)
class Edl:
    timebase: Timebase
    keeps: tuple[Keep, ...]
    resolution: tuple[int, int] | None = None
    sample_rate: int | None = None
    layout: str | None = None

    @property
    def total_frames(self) -> int:
        return sum(k.dur for k in self.keeps)

    @property
    def duration_seconds(self) -> float:
        return self.timebase.to_seconds(self.total_frames)


def _validate(keeps: list[Keep]) -> tuple[Keep, ...]:
    """Enforce the invariants at the boundary.

    The EDL arrives from a foreign tool, so a violation is input validation, not
    an internal bug — and the message must name the offending segment so the
    failure is actionable.
    """
    if not keeps:
        raise EdlError("EDL contains no keep-segments; nothing would be rendered")
    ordered = sorted(keeps, key=lambda k: k.start)
    for k in ordered:
        if k.dur <= 0:
            raise EdlError(f"non-positive duration in segment start={k.start} dur={k.dur}")
        if k.start < 0 or k.offset < 0:
            raise EdlError(f"negative frame index in segment start={k.start} offset={k.offset}")
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        if nxt.start < prev.end:
            raise EdlError(
                f"overlapping segments: [{prev.start}, {prev.end}) and "
                f"[{nxt.start}, {nxt.end})"
            )
    return tuple(ordered)


def _refuse_out_of_scope_effects(clip: dict) -> None:
    """Refuse a v3 clip carrying a timeline feature v1 does not model.

    §3.1 gates the speed vocabulary for `v1` -- "speeds other than 1.0/99999.0
    ... must be rejected explicitly in v1 scope" -- and says nothing about `v3`,
    which is the PRIMARY format. `parse_v3` read `start`, `dur` and `offset` and
    ignored every other key, so the secondary format was defended against a
    hazard the primary format was open to.

    Measured 2026-08-23, auto-editor 31.5.0, `--set-speed 2.0,0,1.5sec
    --export v3`: a speed adjustment is NOT a `speed` field. It appears as

        {"src": ..., "start": 0, "dur": 23, "offset": 0, "stream": 0,
         "effects": ["speed:2.0"]}

    and an ordinary `--edit audio` export carries no `effects` key at all.

    Also measured, and worth recording because it refutes the obvious worry:
    the rendered frame count of that speed timeline was 68, exactly the EDL's
    keep-total -- because `dur` counts OUTPUT frames, not source frames. So
    `_check_render_matches_edl` does NOT misfire on a speed timeline. The gap is
    narrower than it looks and real all the same: `parse` is a public entry
    point, and a timeline whose clips are time-scaled is one v1 has no model
    for. Refused BY NAME, fail-closed on any effect -- an effect nobody has
    measured is not evidence that ignoring it is safe.
    """
    effects = clip.get("effects")
    if effects:
        raise EdlError(
            f"v3 clip at start={clip.get('start')} carries effects {list(effects)}; "
            "v1 scope models plain keep-segments only. A time-scaled or otherwise "
            "processed clip has no representation in cutline's keep-list."
        )


def parse_v3(text: str) -> Edl:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EdlError(f"v3 EDL is not valid JSON: {exc}") from exc
    if str(doc.get("version")) != "3":
        raise EdlError(f"expected a v3 EDL, got version {doc.get('version')!r}")

    tracks = doc.get("v") or []
    clips = tracks[0] if tracks else []
    keeps = []
    for c in clips:
        _refuse_out_of_scope_effects(c)
        keeps.append(
            Keep(start=int(c["start"]), dur=int(c["dur"]), offset=int(c.get("offset", 0)))
        )
    resolution = doc.get("resolution")
    return Edl(
        timebase=Timebase.parse(doc.get("timebase", "")),
        keeps=_validate(keeps),
        resolution=tuple(resolution) if resolution else None,
        sample_rate=doc.get("samplerate"),
        layout=doc.get("layout"),
    )


def parse_v1(text: str) -> Edl:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EdlError(f"v1 EDL is not valid JSON: {exc}") from exc
    if str(doc.get("version")) != "1":
        raise EdlError(f"expected a v1 EDL, got version {doc.get('version')!r}")

    keeps: list[Keep] = []
    cursor = 0
    for chunk in doc.get("chunks", []):
        start, end, speed = int(chunk[0]), int(chunk[1]), float(chunk[2])
        if speed == CUT_SPEED:
            continue
        if speed != KEEP_SPEED:
            raise EdlError(
                f"unsupported speed {speed} in chunk [{start}, {end}); "
                "v1 scope handles keep (1.0) and cut (99999.0) only"
            )
        dur = end - start
        keeps.append(Keep(start=cursor, dur=dur, offset=start))
        cursor += dur

    return Edl(timebase=Timebase.parse(doc.get("timebase", "")), keeps=_validate(keeps))


def parse(path: Path) -> Edl:
    """Dispatch on the suffix auto-editor actually wrote (`.v3` / `.v1`)."""
    path = Path(path)
    text = path.read_text()
    if path.suffix == ".v3":
        return parse_v3(text)
    if path.suffix == ".v1":
        return parse_v1(text)
    raise EdlError(f"unrecognised EDL suffix {path.suffix!r}; expected .v3 or .v1")
