import pytest

from cutline.flow import FlowError, cut
from cutline.probe import probe

pytestmark = pytest.mark.requires_ffmpeg


def test_cut_produces_a_shorter_verified_artifact(silence_mid, tmp_path):
    result = cut(silence_mid, tmp_path)
    assert result.output.exists()
    before, after = probe(silence_mid), probe(result.output)
    assert after.duration < before.duration
    assert result.report.ok, str(result.report)


def test_cut_preserves_rotation_and_the_boundary_proves_it(rotated, tmp_path):
    """auto-editor preserves rotation (measured). The check must confirm it
    rather than assume it — this is the boundary that would catch a regression."""
    result = cut(rotated, tmp_path)
    assert probe(result.output).rotation == probe(rotated).rotation
    assert result.report.ok, str(result.report)


def test_cut_returns_a_parsed_edl_in_frames(silence_mid, tmp_path):
    result = cut(silence_mid, tmp_path)
    assert result.edl.keeps
    assert all(isinstance(k.dur, int) for k in result.edl.keeps)
    assert result.edl.timebase.num > 0


def test_cut_on_continuous_audio_keeps_everything(no_silence, tmp_path):
    result = cut(no_silence, tmp_path)
    before, after = probe(no_silence), probe(result.output)
    assert after.duration == pytest.approx(before.duration, abs=0.3)


def test_no_op_cut_short_circuits_without_re_encoding(no_silence, tmp_path):
    """Spec 5: keeps ~ 100% must not re-encode. A re-encode for a zero-benefit
    cut is pure generation loss, so the output must be byte-identical."""
    result = cut(no_silence, tmp_path)
    assert result.output.read_bytes() == no_silence.read_bytes()


def test_cut_raises_on_a_missing_source(tmp_path):
    with pytest.raises((FileNotFoundError, FlowError)):
        cut(tmp_path / "nope.mp4", tmp_path)
