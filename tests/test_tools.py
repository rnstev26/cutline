import pytest

from cutline.tools import (
    HYPERFRAMES_MIN,
    Tool,
    ToolError,
    discover,
    find_tool,
    require_auto_editor,
    require_hyperframes,
)


def test_find_tool_returns_path_and_version():
    t = find_tool("ffprobe")
    assert isinstance(t, Tool)
    assert t.path.exists()
    assert t.version.startswith("8.")  # measured: 8.1.1 on the target machine


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
    assert t.version.startswith(HYPERFRAMES_MIN)


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
