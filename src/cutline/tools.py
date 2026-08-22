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
FFMPEG_MIN = "8."

# hyperframes is pinned to its MINOR series, not to an exact build like
# auto-editor. Two reasons, both measured rather than assumed:
#
#   * the two measurements available disagree. The final-review brief recorded
#     0.8.7 installed; `hyperframes --version` on this machine reports 0.8.9
#     and `npm ls -g` confirms hyperframes@0.8.9. An exact pin would therefore
#     have refused to run on one of the two environments that ratified it.
#   * what cutline depends on is the render CLI's shape — `hyperframes render`,
#     the `renders/<name>.mp4` output path, and `data-no-timeline` — not an
#     export format the way auto-editor's exact pin protects `--export v3`.
#
# A 0.9 or 1.x bump still refuses, which is the drift this is here to catch.
HYPERFRAMES_MIN = "0.8."

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


def find_tool(name: str, min_version: str | None = None) -> Tool:
    """Locate `name` on PATH and read its version.

    Raises ToolError naming the binary when absent — never returns None, so a
    caller cannot accidentally proceed without the tool.
    """
    found = shutil.which(name)
    if found is None:
        raise ToolError(f"required tool not found on PATH: {name}. {_install_hint(name)}")
    path = Path(found)
    version = _version_of(name, path)
    if min_version and not version.startswith(min_version):
        raise ToolError(f"{name}: found {version}, require {min_version}*")
    return Tool(name=name, path=path, version=version)


def require_auto_editor() -> Tool:
    """auto-editor, and specifically the Nim binary rather than the pip package.

    PyPI serves auto-editor 29.3.1, a Python branch abandoned 2025-11-04. It
    installs without error and answers to the same command name, so detecting it
    by version alone is not enough — a pip install also plants a python shim
    alongside it in the same directory.

    The pip-shim check runs BEFORE version parsing, not after: a pip-installed
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
    sibling_python = path.parent / "python"
    if sibling_python.exists():
        raise ToolError(
            f"auto-editor at {path} looks pip-installed (python shim alongside it). "
            "PyPI serves a dead Python branch; install the Nim binary from "
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
    """hyperframes, pinned to its minor series — see HYPERFRAMES_MIN.

    flow.caption() shelled `["hyperframes", "render"]` by bare PATH name and
    nothing located or pinned it, so a missing install surfaced as a raw
    FileNotFoundError from subprocess rather than spec §5's "fail at startup,
    naming the tool and how to install it", and a version bump could change the
    render CLI underneath us unannounced.
    """
    return find_tool("hyperframes", HYPERFRAMES_MIN)


def discover() -> dict[str, Tool]:
    """Every tool cutline needs, or a ToolError naming the first one missing."""
    return {
        "ffmpeg": find_tool("ffmpeg", FFMPEG_MIN),
        "ffprobe": find_tool("ffprobe", FFMPEG_MIN),
        "auto-editor": require_auto_editor(),
        "hyperframes": require_hyperframes(),
    }
