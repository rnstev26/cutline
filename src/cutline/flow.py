"""Orchestrate the tools and check their work at every handoff.

Nothing here implements media processing. Each stage invokes a tool, locates
what it actually produced, and verifies the artifact against the input under
that boundary's policy. A stage that cannot verify its output raises rather
than handing a suspect artifact to the next stage.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cutline import edl as edl_mod
from cutline.probe import MediaInfo, probe
from cutline.tools import require_auto_editor
from cutline.verify import CUT_POLICY, Report, verify

# Keeping at least this fraction of the source means the cut is effectively a
# no-op, and re-encoding would cost quality for nothing.
NO_OP_RATIO = 0.995


class FlowError(RuntimeError):
    """A stage failed, or produced an artifact that did not survive verification."""


@dataclass
class StageResult:
    name: str
    output: Path
    report: Report
    edl: edl_mod.Edl | None = None
    before: MediaInfo | None = None
    after: MediaInfo | None = None


def _run(argv: list[str], what: str) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FlowError(f"{what} failed (exit {proc.returncode}):\n{proc.stderr.strip()}")


def cut(source: Path, out_dir: Path, margin: str = "0.2sec", edit: str = "audio") -> StageResult:
    """Cut dead air with auto-editor, export the EDL, and verify the render.

    Two auto-editor invocations: one to render, one to export the timeline. They
    are separate because `--export v3` writes the timeline INSTEAD of the video.
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"source does not exist: {source}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tool = require_auto_editor()
    before = probe(source)

    # Export the EDL FIRST so a no-op cut can be detected BEFORE paying for a
    # re-encode. Rendering first and discovering nothing was cut would have cost
    # a full generation-loss pass for no benefit.
    #
    # auto-editor overrides the extension: `-o x.json --export v3` writes `x.v3`.
    # Ask for the stem and find what it actually wrote.
    #
    # out_dir is caller-supplied and may already hold a stale `<stem>_timeline.*`
    # from a prior run — sorted() would then rank it ahead of or behind the fresh
    # export by name alone, and `produced[0]` could silently pick the wrong file.
    # Clear this stage's own glob pattern before exporting so the only match
    # left afterward is the one this call just wrote.
    edl_glob = f"{source.stem}_timeline.*"
    for stale in out_dir.glob(edl_glob):
        stale.unlink()
    edl_stem = out_dir / f"{source.stem}_timeline"
    _run(
        [
            str(tool.path), str(source),
            "--edit", edit,
            "--margin", margin,
            "--export", "v3",
            "-o", str(edl_stem),
        ],
        "auto-editor EDL export",
    )
    produced = sorted(out_dir.glob(edl_glob))
    if not produced:
        raise FlowError(f"auto-editor wrote no EDL matching {edl_stem}.*")
    if len(produced) > 1:
        raise FlowError(
            f"ambiguous EDL export: multiple files matched {edl_stem}.* -> {produced}"
        )
    parsed = edl_mod.parse(produced[0])

    # No-op short-circuit: if the cut would keep essentially everything, copy
    # instead of re-encoding. A re-encode for a ~0% cut is pure generation loss.
    source_frames = before.video.nb_frames if before.video else None
    if source_frames and parsed.total_frames >= source_frames * NO_OP_RATIO:
        rendered = out_dir / f"{source.stem}_cut.mp4"
        shutil.copyfile(source, rendered)
        after = probe(rendered)
        return StageResult(
            name="cut",
            output=rendered,
            report=verify(before, after, CUT_POLICY),
            edl=parsed,
            before=before,
            after=after,
        )

    rendered = out_dir / f"{source.stem}_cut.mp4"
    _run(
        [
            str(tool.path), str(source),
            "--edit", edit,
            "--margin", margin,
            "-o", str(rendered),
        ],
        "auto-editor render",
    )
    if not rendered.exists():
        raise FlowError(f"auto-editor reported success but {rendered} does not exist")

    after = probe(rendered)
    report = verify(before, after, CUT_POLICY)
    if not report.ok:
        raise FlowError(f"cut stage did not survive verification:\n{report}")

    return StageResult(
        name="cut", output=rendered, report=report, edl=parsed, before=before, after=after
    )
