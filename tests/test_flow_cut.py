import json
from dataclasses import replace
from pathlib import Path

import pytest

from cutline.flow import FlowError, cut
from cutline.probe import probe
from cutline.verify import CUT_POLICY, Change, Report, verify

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


@pytest.mark.requires_auto_editor
def test_cut_handles_a_source_stem_with_glob_metacharacters(silence_mid, tmp_path):
    """`my[1].mp4` is an ordinary filename; `[1]` is a glob character class.

    cut() locates auto-editor's EDL by globbing `<stem>_timeline.*`, so an
    unescaped stem makes the pattern match nothing that exists — measured, the
    stage raised "auto-editor wrote no EDL matching .../my[1]_timeline.*" with
    the file present. The Task 6 stale-EDL pre-clean globs the same pattern and
    was void for the same reason. auto-editor handles the name fine.
    """
    awkward = tmp_path / "my[1].mp4"
    awkward.write_bytes(silence_mid.read_bytes())
    out_dir = tmp_path / "out"

    result = cut(awkward, out_dir)

    assert result.output.exists()
    assert result.edl.keeps
    # The pre-clean must have been able to see its own pattern, too: exactly
    # one EDL should remain, and a second call must not trip the ambiguity
    # check by leaving the first one behind.
    again = cut(awkward, out_dir)
    assert again.edl.total_frames == result.edl.total_frames


@pytest.mark.requires_auto_editor
def test_cut_rejects_a_truncated_render(monkeypatch, silence_mid, tmp_path):
    """The reviewer's scenario: auto-editor emits a 0.4-second artifact from a
    12-second source and the boundary report reads `[cut] OK`.

    It reads OK because it SHOULD under CUT_POLICY alone — duration and frame
    count are allowed to shrink at this boundary, and 0.4s is a shrink. The
    first assertion below pins exactly that, so this test cannot later pass for
    the wrong reason: the policy is not what catches truncation, the EDL
    cross-check is.

    The truncation is injected by shrinking what probe() reports for the
    rendered file. auto-editor 31.5.0 does not truncate, so the real defect
    cannot be produced from a fixture — what is under test is cut()'s reaction.
    """
    real_probe = probe
    rendered_name = f"{silence_mid.stem}_cut.mp4"

    def _truncating_probe(path):
        info = real_probe(path)
        if Path(path).name != rendered_name:
            return info
        video = next(s for s in info.streams if s.kind == "video")
        others = tuple(s for s in info.streams if s.kind != "video")
        return replace(
            info,
            duration=0.4,
            streams=(replace(video, nb_frames=12), *others),
        )

    monkeypatch.setattr("cutline.flow.probe", _truncating_probe)

    with pytest.raises(FlowError) as exc:
        cut(silence_mid, tmp_path)
    message = str(exc.value)
    assert "12 frames" in message
    assert "EDL declared" in message


@pytest.mark.requires_auto_editor
def test_the_cut_policy_alone_cannot_see_a_truncation(silence_mid, tmp_path):
    """The other half of the test above: verify() reports OK on a truncated
    artifact, by design. If this ever starts failing, CUT_POLICY has taken on
    the magnitude question and the EDL cross-check needs re-justifying."""
    result = cut(silence_mid, tmp_path)
    before = probe(silence_mid)
    video = next(s for s in result.after.streams if s.kind == "video")
    others = tuple(s for s in result.after.streams if s.kind != "video")
    truncated = replace(
        result.after, duration=0.4, streams=(replace(video, nb_frames=12), *others)
    )
    assert verify(before, truncated, CUT_POLICY).ok
