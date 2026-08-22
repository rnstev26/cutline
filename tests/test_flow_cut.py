import json

import pytest

from cutline.flow import FlowError, cut
from cutline.probe import probe
from cutline.verify import Change, Report

pytestmark = pytest.mark.requires_ffmpeg


@pytest.mark.requires_auto_editor
def test_cut_produces_a_shorter_verified_artifact(silence_mid, tmp_path):
    result = cut(silence_mid, tmp_path)
    assert result.output.exists()
    before, after = probe(silence_mid), probe(result.output)
    assert after.duration < before.duration
    assert result.report.ok, str(result.report)


@pytest.mark.requires_auto_editor
def test_cut_preserves_rotation_and_the_boundary_proves_it(rotated_with_silence, tmp_path):
    """auto-editor preserves rotation (measured). The check must confirm it
    rather than assume it — this is the boundary that would catch a regression.

    Uses `rotated_with_silence`, not `rotated`: the plain `rotated` fixture has
    no silence, so a cut through it keeps 100% of the frames, the no-op
    short-circuit fires, and the output is a `shutil.copyfile` of the source —
    proving only that copyfile preserves rotation, not that auto-editor's
    render does. The assertions below confirm the render path actually ran.
    """
    before = probe(rotated_with_silence)
    result = cut(rotated_with_silence, tmp_path)
    after = probe(result.output)

    # Prove the render path ran, not the no-op copy path.
    assert result.output.read_bytes() != rotated_with_silence.read_bytes()
    assert after.video.nb_frames < before.video.nb_frames

    assert after.rotation == before.rotation
    assert result.report.ok, str(result.report)


@pytest.mark.requires_auto_editor
def test_cut_returns_a_parsed_edl_in_frames(silence_mid, tmp_path):
    result = cut(silence_mid, tmp_path)
    assert result.edl.keeps
    assert all(isinstance(k.dur, int) for k in result.edl.keeps)
    assert result.edl.timebase.num > 0


@pytest.mark.requires_auto_editor
def test_cut_on_continuous_audio_keeps_everything(no_silence, tmp_path):
    result = cut(no_silence, tmp_path)
    before, after = probe(no_silence), probe(result.output)
    assert after.duration == pytest.approx(before.duration, abs=0.3)


@pytest.mark.requires_auto_editor
def test_no_op_cut_short_circuits_without_re_encoding(no_silence, tmp_path):
    """Spec 5: keeps ~ 100% must not re-encode. A re-encode for a zero-benefit
    cut is pure generation loss, so the output must be byte-identical."""
    result = cut(no_silence, tmp_path)
    assert result.output.read_bytes() == no_silence.read_bytes()


def test_cut_raises_on_a_missing_source(tmp_path):
    with pytest.raises((FileNotFoundError, FlowError)):
        cut(tmp_path / "nope.mp4", tmp_path)


@pytest.mark.requires_auto_editor
def test_a_failing_boundary_check_raises_flowerror(monkeypatch, silence_mid, tmp_path):
    """cut() must not hand a suspect artifact onward when verify() finds a
    violation. auto-editor legitimately preserves every invariant CUT_POLICY
    checks, so a genuine failure cannot be produced from a real fixture — inject
    one by making verify() report a violation, and confirm cut() stops rather
    than proceeding.

    silence_mid has real silence to cut, so this exercises the render path
    (not the no-op short-circuit), which is where the render's own report is
    checked and used to decide whether to raise.
    """

    def _fake_verify(before, after, policy):
        report = Report(boundary=policy.name)
        report.changes.append(Change(prop="rotation", before=90, after=0))
        return report

    monkeypatch.setattr("cutline.flow.verify", _fake_verify)

    with pytest.raises(FlowError, match="rotation"):
        cut(silence_mid, tmp_path)


@pytest.mark.requires_auto_editor
def test_cut_ignores_a_stale_edl_left_in_the_output_dir(silence_mid, tmp_path):
    """A stale <stem>_timeline.v1 pre-existing in out_dir must not be picked
    over the fresh export. Reproduces the scenario found in review: sorted()
    could otherwise rank the stale .v1 ahead of the fresh .v3, and
    produced[0] would silently hand the wrong EDL to the caller — corrupting
    the edl field on StageResult and potentially inverting the no-op
    short-circuit decision."""
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    baseline = cut(silence_mid, baseline_dir)

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    stale = target_dir / f"{silence_mid.stem}_timeline.v1"
    stale.write_text(json.dumps({"version": "1", "timebase": "30/1", "chunks": [[0, 1, 1.0]]}))

    result = cut(silence_mid, target_dir)

    assert result.edl.total_frames != 1, "cut() picked up the stale 1-frame EDL"
    assert result.edl.total_frames == baseline.edl.total_frames
