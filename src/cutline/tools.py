"""Locate external binaries and pin their versions.

cutline shells out to every media tool it uses. This module is the single place
that decides whether a tool is present, which one it found, and whether its
version is acceptable — so no other module has to guess.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

AUTO_EDITOR_VERSION = "31.5.0"

# ffmpeg wants a real FLOOR, not a series pin: cutline's own source uses
# nothing newer than roughly ffmpeg 3 (signalstats, blackframe,
# metadata=print, movie=, read_intervals, -show_streams, -show_format, and
# standard flags). The newest feature anywhere in the project is
# `-display_rotation`, used only in the test suite's fixture generation
# (tests/conftest.py), which landed in ffmpeg 6.0. So 6 is the actual
# requirement, measured against the test suite rather than assumed from a
# round number — and unlike a series pin, ffmpeg 9, 10, ... must keep passing,
# because nothing about cutline's usage changes above the floor.
FFMPEG_FLOOR = "6"

# hyperframes is pinned to its MINOR series, not to an exact build like
# auto-editor. Two reasons, both measured rather than assumed:
#
#   * the version MOVES under us, unattended, on a timescale of hours, not
#     months: observed changing THREE times in one working day (2026-08-22/23)
#     on this same machine — the last move happened while a comment about the
#     previous one was being written, which is why this comment no longer
#     cites version numbers as evidence. Any specific pair quoted here would
#     already be stale by the time it was read; the pattern is the durable
#     fact, not the numbers. The practical symptom is that the binary is
#     briefly unresolvable mid-update, which surfaces as intermittent
#     tool-not-found failures in tool-discovery tests — real, not a flaky
#     test, if you see it again. An exact pin would have broken three times in
#     a single day; a series pin absorbs all three and still refuses a 0.9 or
#     1.x bump. Confirmed: this pin accepted 0.8.10, the latest of the three
#     moves, with no change required.
#   * what cutline depends on is the render CLI's shape — `hyperframes render`,
#     the `renders/<name>.mp4` output path, and `data-no-timeline` — not an
#     export format the way auto-editor's exact pin protects `--export v3`.
#
# A 0.9 or 1.x bump still refuses, which is the drift this is here to catch.
HYPERFRAMES_SERIES = "0.8."

# Spec §5: a missing tool must "fail at startup, naming the tool AND how to
# install it". The name alone was all find_tool gave.
INSTALL_HINTS = {
    "ffmpeg": "brew install ffmpeg, or your distribution's ffmpeg package",
    "ffprobe": "ships with ffmpeg: brew install ffmpeg, or your distro's package",
    "auto-editor": (
        "download the Nim binary from "
        "https://github.com/WyattBlue/auto-editor/releases — NOT pip"
    ),
    "hyperframes": "npm install -g hyperframes",
}


class ToolError(RuntimeError):
    """A required external tool is missing, wrong, or unusable."""


@dataclass(frozen=True)
class Tool:
    name: str
    path: Path
    version: str


_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _meets_floor(version: str, floor: str) -> bool:
    """version >= floor, comparing numeric components so 9.0 satisfies "6".

    This is the semantic ffmpeg needs: unlike a series pin, a newer major must
    keep passing. Shorter tuples are zero-padded so "6" as a floor and "6.1.1"
    as a version compare as (6, 0, 0) <= (6, 1, 1).
    """
    v = _parse_version(version)
    f = _parse_version(floor)
    width = max(len(v), len(f))
    v = v + (0,) * (width - len(v))
    f = f + (0,) * (width - len(f))
    return v >= f


def _meets_series(version: str, series: str) -> bool:
    """version belongs to the given minor `series`, e.g. "0.8.9" in "0.8.".

    This is prefix equality, not a floor: it is what hyperframes needs (a 0.9
    or 1.x bump must still refuse), and it is deliberately NOT what ffmpeg
    needs — see FFMPEG_FLOOR above for why a floor is a different guarantee.
    """
    return version.startswith(series)


def _run(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
        raise ToolError(f"could not execute {argv[0]}: {exc}") from exc
    return (proc.stdout or "") + (proc.stderr or "")


def _version_of(name: str, path: Path) -> str:
    flag = "--version"
    out = _run([str(path), flag])
    match = _VERSION_RE.search(out)
    if not match:
        raise ToolError(f"{name}: could not parse a version from `{name} {flag}` output")
    return match.group(1)


def _install_hint(name: str) -> str:
    hint = INSTALL_HINTS.get(name)
    return f"Install it: {hint}" if hint else "No install hint is recorded for this tool."


def find_tool(name: str, *, floor: str | None = None, series: str | None = None) -> Tool:
    """Locate `name` on PATH and read its version.

    Raises ToolError naming the binary when absent — never returns None, so a
    caller cannot accidentally proceed without the tool.

    `floor` and `series` are two different, deliberately distinguishable
    semantics, not two names for the same check:

      * `floor` is a minimum — version >= floor, so a newer major still
        passes (ffmpeg 9 must satisfy a floor of "6"). Use this when nothing
        about cutline's usage changes above the requirement.
      * `series` is a minor-series pin — prefix equality, so a version OUTSIDE
        the series is refused even if it is newer (hyperframes 0.9.x must
        still refuse a "0.8." series pin). Use this when the CLI's shape is
        only known to hold within that series.

    Passing both is not a supported combination — no current caller needs it,
    and it would be ambiguous which rejection message wins.
    """
    if floor is not None and series is not None:
        raise ValueError("find_tool: pass at most one of floor= or series=, not both")
    found = shutil.which(name)
    if found is None:
        raise ToolError(f"required tool not found on PATH: {name}. {_install_hint(name)}")
    path = Path(found)
    version = _version_of(name, path)
    if floor is not None and not _meets_floor(version, floor):
        raise ToolError(f"{name}: found {version}, require >= {floor}")
    if series is not None and not _meets_series(version, series):
        raise ToolError(f"{name}: found {version}, require {series}*")
    return Tool(name=name, path=path, version=version)


def _is_compiled_executable(path: Path) -> bool:
    """Is this a compiled binary, or a script pretending to be one?

    Positive identification, replacing a proximity heuristic. The previous rule
    was "a file named `python` sits next to it", and §9 sends everyone to
    install the CORRECT binary into `~/.local/bin` — a directory that very
    commonly also holds a `python` from pipx or uv. Measured 2026-08-23: with a
    `python` placed beside a symlink to the genuine 31.5.0 Nim binary,
    `require_auto_editor()` refused the good install:

        REFUSED: auto-editor at .../auto-editor looks pip-installed (python
        shim alongside it).

    It was false-negative-prone in the other direction too: a pip install into
    any layout WITHOUT that sibling passed, and was then caught only by the
    version pin — a different refusal with a different message, so the operator
    was told "wrong version" for a problem that is "wrong project".

    What actually distinguishes them is measurable on the file itself. Measured
    on this machine, two independent Python tool-chains (pipx and uv) both
    produce console scripts that are TEXT beginning with `#!`:

        #!/bin/sh
        #!/Users/.../bin/python

    while the genuine release is a compiled image:

        Mach-O 64-bit executable arm64,  magic cf fa ed fe
        sha256 58d8893a389df60223b2a9d9f1307451d1581e1965c5f0e2e626c95024dbcca3
        26,117,768 bytes            (both re-measured 2026-08-23, still §9's)

    The hash is deliberately NOT the gate: §9's value is one platform's asset,
    and pinning it would refuse a legitimate Linux or x86_64 build. The shebang
    is the property that actually differs between the two projects.
    """
    try:
        with path.open("rb") as fh:
            return fh.read(2) != b"#!"
    except OSError:
        # Unreadable: fail closed. A file we could not inspect is not evidence
        # that it is the pinned release.
        return False


def require_auto_editor() -> Tool:
    """auto-editor, and specifically the Nim binary rather than the pip package.

    PyPI serves auto-editor 29.3.1, a Python branch abandoned 2025-11-04. It
    installs without error and answers to the same command name, so detecting it
    by version alone is not enough.

    The identification runs BEFORE version parsing, not after: a pip-installed
    auto-editor's `--version` output is not guaranteed to parse cleanly (or to
    run at all), so parsing first can raise an unrelated "could not parse a
    version" error that masks the actual, more useful diagnosis.
    """
    found = shutil.which("auto-editor")
    if found is None:
        raise ToolError(
            f"required tool not found on PATH: auto-editor. {_install_hint('auto-editor')}"
        )
    path = Path(found)
    if not _is_compiled_executable(path):
        raise ToolError(
            f"auto-editor at {path} is not the pinned release: it is a script, not "
            "a compiled binary, which is the shape pip / pipx / uv console scripts "
            "have. PyPI serves a dead Python branch; install the Nim binary from "
            "https://github.com/WyattBlue/auto-editor/releases instead."
        )
    tool = find_tool("auto-editor")
    if tool.version != AUTO_EDITOR_VERSION:
        raise ToolError(
            f"auto-editor: found {tool.version}, pinned to {AUTO_EDITOR_VERSION}. "
            "Update the pin deliberately after re-measuring the export format."
        )
    return tool


def require_hyperframes() -> Tool:
    """hyperframes, pinned to its minor series — see HYPERFRAMES_SERIES.

    flow.caption() shelled `["hyperframes", "render"]` by bare PATH name and
    nothing located or pinned it, so a missing install surfaced as a raw
    FileNotFoundError from subprocess rather than spec §5's "fail at startup,
    naming the tool and how to install it", and a version bump could change the
    render CLI underneath us unannounced.
    """
    return find_tool("hyperframes", series=HYPERFRAMES_SERIES)


def discover() -> dict[str, Tool]:
    """Every tool cutline needs, or a ToolError naming the first one missing."""
    return {
        "ffmpeg": find_tool("ffmpeg", floor=FFMPEG_FLOOR),
        "ffprobe": find_tool("ffprobe", floor=FFMPEG_FLOOR),
        "auto-editor": require_auto_editor(),
        "hyperframes": require_hyperframes(),
    }
