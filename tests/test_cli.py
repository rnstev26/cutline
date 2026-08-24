import pytest
from typer.testing import CliRunner

from cutline.cli import app
from cutline.flow import FlowError

runner = CliRunner()


@pytest.mark.requires_auto_editor
@pytest.mark.requires_hyperframes
def test_doctor_lists_every_tool_and_version():
    """Needs the auto-editor and hyperframes binaries. CI installs only ffmpeg,
    so this is marked and deselected there — see Task 9.

    Spec §4 assigns tools.py all four tools; `doctor` printed three rows and
    hyperframes was in neither it nor discover()."""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    for tool in ("ffmpeg", "ffprobe", "auto-editor", "hyperframes"):
        assert tool in result.stdout, f"doctor did not report {tool}"
    assert "31.5.0" in result.stdout


def test_probe_prints_rotation_when_present(rotated):
    result = runner.invoke(app, ["probe", str(rotated)])
    assert result.exit_code == 0
    assert "rotation" in result.stdout.lower()
    assert "90" in result.stdout


def test_probe_exits_nonzero_on_a_missing_file(tmp_path):
    result = runner.invoke(app, ["probe", str(tmp_path / "nope.mp4")])
    assert result.exit_code != 0


def test_an_edl_error_exits_cleanly_rather_than_tracebacking(monkeypatch, tmp_path):
    """`edl.EdlError` subclasses ValueError, and the CLI caught FlowError,
    ToolError and FileNotFoundError only — so a rejected EDL escaped as a
    traceback rather than §5's "fail with the offending segment printed".

    Reachable today: `_refuse_out_of_scope_effects` raises EdlError from inside
    `cut()`, so any timeline auto-editor exports that v1 does not model takes
    this path.
    """
    from cutline import cli as cli_mod
    from cutline.edl import EdlError

    def boom(*a, **k):
        raise EdlError("v3 clip at start=0 carries effects ['speed:2.0']")

    monkeypatch.setattr(cli_mod, "cut_stage", boom)
    src = tmp_path / "x.mp4"
    src.write_bytes(b"")
    result = runner.invoke(app, ["cut", str(src), "--out", str(tmp_path / "o")])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "effects" in result.output


def test_cut_exposes_the_margin_and_edit_parameters(monkeypatch, tmp_path):
    """F17: `flow.cut()` has taken `margin` and `edit` since it was written and
    the CLI exposed neither, so auto-editor's edit expression and margin — the
    two settings that decide whether a cut is USABLE rather than merely intact —
    were unreachable without editing the source.
    """
    from cutline import cli as cli_mod

    seen = {}

    def spy(source, out, *, margin, edit):
        seen.update(margin=margin, edit=edit)
        raise FlowError("stop here; the call shape is what this test is about")

    monkeypatch.setattr(cli_mod, "cut_stage", spy)
    src = tmp_path / "x.mp4"
    src.write_bytes(b"")
    runner.invoke(app, ["cut", str(src), "--margin", "0.3s,1.5sec", "--edit", "motion"])
    assert seen == {"margin": "0.3s,1.5sec", "edit": "motion"}
