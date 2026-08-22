"""Command-line surface. Thin: every command delegates immediately."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cutline.flow import FlowError
from cutline.flow import caption as caption_stage
from cutline.flow import cut as cut_stage
from cutline.flow import run as run_flow
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
    source: Path, out: Annotated[Path, typer.Option("--out")] = Path("out")
) -> None:
    """Cut dead air with auto-editor and verify the artifact."""
    try:
        _report([cut_stage(source, out)])
    except (FlowError, ToolError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def caption(
    source: Path, project: Path, out: Annotated[Path, typer.Option("--out")] = Path("out")
) -> None:
    """Composite captions with HyperFrames and verify the artifact."""
    try:
        _report([caption_stage(source, project, out)])
    except (FlowError, ToolError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def run(
    source: Path, project: Path, out: Annotated[Path, typer.Option("--out")] = Path("out")
) -> None:
    """The full v1 flow: cut, verify, caption, verify."""
    try:
        _report(run_flow(source, project, out))
    except (FlowError, ToolError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
