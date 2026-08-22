import pytest

from cutline.tools import Tool, ToolError, find_tool, require_auto_editor


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
