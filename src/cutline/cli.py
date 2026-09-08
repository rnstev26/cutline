"""Command-line surface. Thin: every command delegates immediately."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cutline.edl import EdlError
from cutline.flow import FlowError
from cutline.flow import caption as caption_stage
from cutline.flow import cut as cut_stage
from cutline.flow import run as run_flow
from cutline.issues import find_issues_in_srt
from cutline.probe import probe as probe_file
from cutline.tools import ToolError, discover

app = typer.Typer(
    help="A verification spine for a two-source video pipeline.", no_args_is_help=True
)


@app.command()
def doctor() -> None:
    """Report every external tool cutline needs, and its version."""
    try:
        for name, tool in discover().items():
            typer.echo(f"  ok  {name:<12} {tool.version:<10} {tool.path}")
    except ToolError as exc:
        typer.echo(f"  FAIL  {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def probe(path: Path) -> None:
    """Print every property cutline verifies for a media file."""
    try:
        info = probe_file(path)
    except (FileNotFoundError, ToolError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"path      {info.path}")
    typer.echo(f"duration  {info.duration:.3f}")
    typer.echo(f"rotation  {info.rotation}")
    for s in info.streams:
        typer.echo(
            f"  {s.kind:<6} codec={s.codec} {s.width}x{s.height} "
            f"sar={s.sar} rate={s.sample_rate} ch={s.channels} start={s.start_time:.6f}"
        )


def _report(results) -> None:
    for r in results:
        typer.echo(str(r.report))
        typer.echo(f"  -> {r.output}")


@app.command()
def cut(
    source: Path,
    out: Annotated[Path, typer.Option("--out")] = Path("out"),
    # The two parameters that decide whether the cut is USABLE rather than
    # merely intact. `flow.cut()` has taken them since it was written and the
    # CLI exposed neither, so the only way to change a margin was to edit the
    # source — while §0 celebrates asymmetric margins as a capability rev 1
    # lacked. An artifact that passes every boundary check and clips the
    # operator's word onsets satisfies "verified" and fails "usable".
    #
    # The defaults are auto-editor's own (`--margin 0.2s`, `--edit audio`),
    # unchanged, so this adds a knob and moves no behaviour.
    margin: Annotated[str, typer.Option("--margin")] = "0.2sec",
    edit: Annotated[str, typer.Option("--edit")] = "audio",
) -> None:
    """Cut dead air with auto-editor and verify the artifact."""
    try:
        _report([cut_stage(source, out, margin=margin, edit=edit)])
    except (FlowError, ToolError, EdlError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def caption(
    source: Path, project: Path, out: Annotated[Path, typer.Option("--out")] = Path("out")
) -> None:
    """Composite captions with HyperFrames and verify the artifact."""
    try:
        _report([caption_stage(source, project, out)])
    except (FlowError, ToolError, EdlError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def run(
    source: Path, project: Path, out: Annotated[Path, typer.Option("--out")] = Path("out")
) -> None:
    """The full v1 flow: cut, verify, caption, verify."""
    try:
        _report(run_flow(source, project, out))
    except (FlowError, ToolError, EdlError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def issues(
    transcript: Path,
    phrase: Annotated[int, typer.Option("--phrase")] = 4,
    window: Annotated[float, typer.Option("--window")] = 30.0,
) -> None:
    """Report re-takes, false starts and stutters in a transcript. Never edits.

    There is deliberately no --fix. A third-party editor's equivalent deleted
    15 words for 6 reported removals -- every deletion took the following word
    with it -- and its restore verb reported 8 restores while performing 2 and
    destroyed 96 unrelated silence trims. Detection is safe; deletion is not,
    and the operator rules on every candidate.

    Exit 1 only on medium/high. Low is review-class: a restart that diverges
    from its fragment is usually deliberate parallel structure.
    """
    if not transcript.is_file():
        typer.echo(f"no such transcript: {transcript}", err=True)
        raise typer.Exit(1)
    report = find_issues_in_srt(transcript.read_text(), phrase=phrase, window=window)
    typer.echo(str(report))
    if not report.ok:
        raise typer.Exit(1)
