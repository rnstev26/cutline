import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cutline import flow as flow_mod
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


@pytest.mark.requires_auto_editor
def test_a_container_without_a_header_frame_count_still_verifies(
    fragmented_source, tmp_path
):
    """The recording-readiness case: a crash-safe container, cut and verified.

    Measured on this fixture before the fix, `cut()` refused a healthy render:

        [cut] FAILED
          violation: video.nb_frames: None -> 282 (this boundary permits a
                     shrink, not a growth)

    Nothing had shrunk or grown — one side was simply unmeasured, and `_grew`
    fails closed on an unreadable side. The resolution is that `probe()` now
    MEASURES the count when the header omits it, so the comparison is between
    two numbers. Deleting the direction constraint would have made this pass
    too, and would have removed the check instead of the unknown.
    """
    result = cut(fragmented_source, tmp_path)
    assert result.report.ok, str(result.report)
    before, after = probe(fragmented_source), probe(result.output)
    assert before.video.nb_frames is not None
    assert after.video.nb_frames < before.video.nb_frames
    assert after.duration < before.duration


@pytest.mark.requires_auto_editor
def test_variable_frame_rate_source_cuts_and_verifies(variable_frame_rate, tmp_path):
    """F3's unexamined case, examined.

    Every other fixture is synthetic CFR at 30fps, so the suite could not say
    whether the frame-count identity gate survives a source whose presented
    cadence is uneven — and §2 names phone footage, which measurably is, as the
    ordinary input. This does not prove VFR is universally safe; it proves the
    gate is not vacuously green because no fixture could reach it.
    """
    result = cut(variable_frame_rate, tmp_path)
    assert result.report.ok, str(result.report)


@pytest.mark.requires_auto_editor
def test_a_real_cut_is_not_classified_a_no_op_when_audio_outruns_video(
    fixture_dir, tmp_path
):
    """The no-op gate must compare TIMELINE frames to TIMELINE frames.

    It used to compare the EDL's keep-total (timeline frames) against
    `video.nb_frames` (video-STREAM frames). Those differ whenever the
    container's declared duration exceeds the video stream's length, and the
    consequence was the §2 failure shape exactly: measured on this source
    (6s of video, 12s of audio, silence at 3-5s and 8-9.5s) auto-editor's EDL
    kept 281 of 360 timeline frames — a real cut — and 281 >= 180 * 0.995
    classified it a no-op, so the SOURCE was copied through byte-for-byte
    unedited and the boundary reported `[cut] OK`.

    Two assertions, because the report is exactly what the bug corrupted. The
    unit one pins the quantity; the integration one pins the consequence — with
    the gate reverted to `video.nb_frames`, `cut()` returns a StageResult whose
    output is byte-identical to the source and whose report reads OK, so NO
    exception is raised and the `pytest.raises` below fails. (Refusing this
    particular source is itself correct: auto-editor renders the full 360-frame
    timeline, i.e. 281 frames of video where the source stream had 180, and a
    cut that lengthens the video stream is a real difference to report.)
    """
    source = fixture_dir / "audio_outruns_video.mp4"
    if not source.exists():
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=6:r=30",
             "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
             "-af", "volume=enable='between(t,3,5)+between(t,8,9.5)':volume=0",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
            check=True, capture_output=True, text=True,
        )
    before = probe(source)
    assert before.video.nb_frames == 180, "fixture must have a 6s video stream"

    edl = flow_mod.edl_mod.Edl(
        timebase=flow_mod.edl_mod.Timebase(30, 1),
        keeps=(flow_mod.edl_mod.Keep(start=0, dur=281, offset=0),),
    )
    assert flow_mod._source_timeline_frames(before, edl) == 360, (
        "the source's length in the EDL's own units is 12s * 30fps, not the "
        "video stream's 180 frames"
    )

    with pytest.raises(FlowError, match="nb_frames"):
        cut(source, tmp_path)
    rendered = tmp_path / f"{source.stem}_cut.mp4"
    assert rendered.exists() and rendered.read_bytes() != source.read_bytes(), (
        "the source was copied through unedited: the no-op gate compared the "
        "EDL's timeline frames against the video stream's frame count"
    )


@pytest.mark.requires_auto_editor
def test_an_edl_claiming_more_than_the_source_is_refused(
    monkeypatch, silence_mid, tmp_path
):
    """F1: `edl._validate`'s invariants are all properties of the keep-list
    considered ALONE, so an EDL claiming frames past the end of the source
    parsed clean and reached the render — where the only quantitative gate
    compares the render against THAT SAME EDL, so an over-claiming EDL and a
    padded render agree with each other.

    Substituting a parse result is the honest way to reach this: auto-editor
    31.5.0 does not produce such an EDL, and a test that could only fire if it
    did would be a guard on a target the code never writes.
    """
    real_parse = flow_mod.edl_mod.parse

    def over_claiming(path):
        parsed = real_parse(path)
        fat = replace(parsed.keeps[0], dur=parsed.keeps[0].dur + 100_000)
        return replace(parsed, keeps=(fat, *parsed.keeps[1:]))

    monkeypatch.setattr(flow_mod.edl_mod, "parse", over_claiming)
    with pytest.raises(FlowError, match="carries only"):
        cut(silence_mid, tmp_path)


@pytest.mark.requires_auto_editor
def test_the_source_video_profile_survives_the_cut(fixture_dir, tmp_path):
    """§4.1 makes `video.profile` an invariant of this boundary. Measured on a
    real Apple-written `.mov` (H.264 **Main**), auto-editor rendered H.264
    **High** — its libx264 default — and the cut was refused:

        [cut] FAILED
          violation: video.profile: 'Main' -> 'High'

    on a healthy render. `flow._profile_args` declares the source's profile to
    the renderer rather than hoping for it. This fixture reproduces the input
    shape (a Main-profile source) without depending on a file outside the repo.
    """
    source = fixture_dir / "main_profile.mp4"
    if not source.exists():
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=12:r=30",
             "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
             "-af", "volume=enable='between(t,3,5)+between(t,8,9.5)':volume=0",
             "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(source)],
            check=True, capture_output=True, text=True,
        )
    before = probe(source)
    assert before.video.profile == "Main", "fixture must actually be Main profile"
    result = cut(source, tmp_path)
    assert result.report.ok, str(result.report)
    assert probe(result.output).video.profile == "Main"
