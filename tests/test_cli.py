import pytest
from typer.testing import CliRunner

from cutline.cli import app

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
