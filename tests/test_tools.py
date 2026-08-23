import re

import pytest

from cutline.tools import (
    FFMPEG_FLOOR,
    HYPERFRAMES_SERIES,
    Tool,
    ToolError,
    discover,
    find_tool,
    require_auto_editor,
    require_hyperframes,
)


def test_find_tool_returns_path_and_version():
    r"""Asserts the PARSING SURFACE, which is what cutline actually depends on,
    rather than the operator's exact major.

    `assert t.version.startswith("8.")` was the previous assertion and it
    carried no marker, so CI selected it and it failed deterministically on
    Linux. A floor plus a shape assertion is not vacuous: if `_VERSION_RE` or
    `_version_of` ever returned something that is not a version, the fullmatch
    below goes red — mutating the regex to `(\d+)` reddens it, measured.
    """
    t = find_tool("ffprobe")
    assert isinstance(t, Tool)
    assert t.path.exists()
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", t.version), (
        f"cutline parsed {t.version!r} out of `ffprobe --version` — not a version"
    )
    assert int(t.version.split(".")[0]) >= int(FFMPEG_FLOOR)


def test_ffmpeg_meets_its_own_floor_everywhere_cutline_runs():
    """FFMPEG_FLOOR replaces what used to be a `requires_pinned_ffmpeg`-marked,
    CI-deselected test asserting an 8.x SERIES pin the Linux runner (6.1.1)
    could never satisfy.

    A floor is a different guarantee than a series pin, and it is satisfiable
    everywhere cutline runs, including ubuntu-latest — so unlike its
    predecessor this test carries no marker and is never deselected: if
    find_tool raises here, FFMPEG_FLOOR has been set above what a runner
    actually ships, and this is the test that says so honestly rather than a
    marker quietly hiding the gap.
    """
    tool = find_tool("ffmpeg", floor=FFMPEG_FLOOR)
    assert isinstance(tool, Tool)


def test_a_below_floor_ffmpeg_is_refused(tmp_path, monkeypatch):
    """The floor has to be able to refuse, or it is decoration."""
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho 5.1.3\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ToolError, match="5.1.3"):
        find_tool("ffmpeg", floor=FFMPEG_FLOOR)


def test_an_above_floor_ffmpeg_is_accepted(tmp_path, monkeypatch):
    """The defect this fixes: the old prefix-equality check
    (`version.startswith("8.")`) refused ffmpeg 9.x outright. A real floor
    must accept anything at or above it, including a major cutline has never
    been tested against."""
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho 9.0.2\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    tool = find_tool("ffmpeg", floor=FFMPEG_FLOOR)
    assert tool.version == "9.0.2"


def test_find_tool_raises_naming_the_missing_binary():
    with pytest.raises(ToolError) as exc:
        find_tool("definitely-not-a-real-binary")
    assert "definitely-not-a-real-binary" in str(exc.value)


@pytest.mark.requires_auto_editor
def test_require_auto_editor_accepts_the_nim_binary():
    t = require_auto_editor()
    assert t.version == "31.5.0"


def test_require_auto_editor_rejects_a_pip_install(tmp_path, monkeypatch):
    """A pip-installed auto-editor lives beside a python shim and is the dead branch."""
    fake = tmp_path / "auto-editor"
    fake.write_text("#!/usr/bin/env python\n")
    fake.chmod(0o755)
    (tmp_path / "python").write_text("")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ToolError) as exc:
        require_auto_editor()
    assert "pip" in str(exc.value).lower()


@pytest.mark.requires_hyperframes
def test_require_hyperframes_locates_and_pins_it():
    """Spec §4 assigns tools.py "locate + version-pin auto-editor, ffmpeg,
    hyperframes". hyperframes was in neither discover() nor `cutline doctor`;
    flow.caption() shelled it by bare PATH name."""
    t = require_hyperframes()
    assert t.path.exists()
    assert t.version.startswith(HYPERFRAMES_SERIES)


@pytest.mark.requires_auto_editor
@pytest.mark.requires_hyperframes
def test_discover_reports_all_four_tools():
    assert set(discover()) == {"ffmpeg", "ffprobe", "auto-editor", "hyperframes"}


def test_a_missing_tool_is_reported_with_how_to_install_it(tmp_path, monkeypatch):
    """Spec §5: "fail at startup, naming the tool AND how to install it". The
    name alone was all find_tool used to give."""
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ToolError) as exc:
        require_hyperframes()
    message = str(exc.value)
    assert "hyperframes" in message
    assert "npm install -g hyperframes" in message


def test_a_version_outside_the_hyperframes_pin_is_refused(tmp_path, monkeypatch):
    """The pin has to be able to refuse, or it is decoration. A fake reporting
    0.9.0 must be rejected while the real 0.8.x is accepted."""
    fake = tmp_path / "hyperframes"
    fake.write_text("#!/bin/sh\necho 0.9.0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ToolError, match="0.9.0"):
        require_hyperframes()
