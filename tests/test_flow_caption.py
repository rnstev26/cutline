import pytest

from cutline.flow import (
    BLACK_FRAME_RATIO_THRESHOLD,
    BLACK_PIXEL_LUMA_CEILING,
    FlowError,
    _run,
    black_pixel_ratio,
    caption,
    mean_luma,
    run,
)
from cutline.tools import ToolError
from cutline.verify import COMPOSITE_POLICY, Change, Report

pytestmark = pytest.mark.requires_ffmpeg


@pytest.mark.requires_hyperframes
def test_caption_stage_warns_but_does_not_fail_on_resampled_audio(
    hf_project, silence_mid, tmp_path
):
    """Measured: HyperFrames turns 44.1kHz mono into 48kHz stereo unannounced.
    That is legitimate for a re-composite and must warn, not fail."""
    result = caption(silence_mid, hf_project, tmp_path)
    assert result.report.ok
    assert any("audio" in w.prop for w in result.report.warnings)


@pytest.mark.requires_hyperframes
def test_caption_stage_uses_the_composite_policy(hf_project, silence_mid, tmp_path):
    result = caption(silence_mid, hf_project, tmp_path)
    assert result.report.boundary == COMPOSITE_POLICY.name


@pytest.mark.requires_hyperframes
def test_caption_output_is_not_a_black_frame(hf_project, silence_mid, tmp_path):
    """A correctly-sized black video passes every metadata assertion."""
    result = caption(silence_mid, hf_project, tmp_path)
    assert black_pixel_ratio(result.output) < BLACK_FRAME_RATIO_THRESHOLD


@pytest.mark.requires_auto_editor
@pytest.mark.requires_hyperframes
def test_run_executes_both_stages_in_order(hf_project, silence_mid, tmp_path):
    """run() chains cut() (auto-editor) into caption() (hyperframes) — the
    only test in this project needing both external tools at once."""
    results = run(silence_mid, hf_project, tmp_path)
    assert [r.name for r in results] == ["cut", "caption"]


@pytest.mark.requires_auto_editor
@pytest.mark.requires_hyperframes
def test_run_on_a_portrait_source_survives_the_black_frame_guard(
    hf_project, rotated_with_silence, tmp_path
):
    """Spec §8's v1 criterion names *rotation on a portrait source*, and until
    now no caption or run test used one: every one used `silence_mid`, which is
    landscape and fills the canvas edge to edge.

    That omission hid a live defect. HyperFrames contains a 9:16 source inside
    its 16:9 canvas, so 68% of every frame is pillarbox at the limited-range
    black floor. Against the previous WHOLE-FRAME MEAN gate this correct render
    measured 21.227 against a 20.0 threshold — a 6% margin, so any portrait
    source darker than a synthetic navy card would have been rejected as
    "essentially black" while rendering perfectly.

    This test is the acceptance case itself, and it asserts the margin rather
    than merely that the call returned: a future change that re-dilutes the
    measurement with the bars reddens here.
    """
    results = run(rotated_with_silence, hf_project, tmp_path)
    assert [r.name for r in results] == ["cut", "caption"]

    captioned = results[-1].output
    ratio = black_pixel_ratio(captioned)
    assert ratio < BLACK_FRAME_RATIO_THRESHOLD, (
        f"the portrait acceptance case measured {ratio:.4f} black pixels — at "
        f"or over the {BLACK_FRAME_RATIO_THRESHOLD} gate, so a correct render "
        "is being rejected"
    )
    # Measured 0.684, the geometric maximum for pillarboxing 9:16 into 16:9.
    # Asserting the neighbourhood, not just "below the gate", keeps this from
    # passing vacuously if the composition ever stops pillarboxing at all — in
    # which case the case stops being the one spec §8 names.
    assert 0.6 < ratio < 0.75, (
        f"expected ~0.684 of the frame to be pillarbox, measured {ratio:.4f} — "
        "this is no longer the pillarboxed-portrait case"
    )


def test_black_pixel_ratio_discriminates_black_from_content(black_frame, silence_mid):
    """The gate's premise, checked directly and unpatched, in both directions.

    Real ffmpeg-black is Y~16 (the limited-range floor), not 0, so the pixel
    ceiling has to sit above 16 without reaching real content. If either the
    ceiling or the measurement were broken to a constant, one of these goes red.
    """
    black = black_pixel_ratio(black_frame)
    content = black_pixel_ratio(silence_mid)

    assert black >= BLACK_FRAME_RATIO_THRESHOLD, (
        f"black fixture measured {black} black pixels — under the gate, "
        "so the gate could never fire on real black"
    )
    assert black == pytest.approx(1.0, abs=0.01), (
        f"expected an all-black fixture to read ~1.0, got {black}"
    )
    # Measured on this project's navy-background fixture: 0.0 — the whole frame
    # sits above the BLACK_PIXEL_LUMA_CEILING at Y~28.5. The old mean-based
    # control could only say 35.9 > 20; this says the two are not merely
    # ordered but separated by the entire range.
    assert content == pytest.approx(0.0, abs=0.01), (
        f"real content measured {content} black pixels — too close to the "
        "black fixture to prove the two are distinguishable"
    )
    assert mean_luma(black_frame) < mean_luma(silence_mid)


def test_luma_probe_samples_the_whole_timeline_not_just_the_head(black_after_head):
    """A clip that is fine at the head and black afterwards must fail the gate.

    The previous probe read `-read_intervals "%+#20"` — twenty frames, the first
    0.67 seconds at 30fps. Measured on this fixture that sampling reports mean
    luma 235.0 and no black pixels at all; sampled across the whole timeline the
    same file reports mean luma 34.25 and 91.67% black pixels.

    The head assertion below is the positive control: it proves the fixture
    really is bright where the old probe looked, so this test fails for the
    right reason rather than because the clip is black everywhere.
    """
    ratio = black_pixel_ratio(black_after_head)
    assert ratio >= BLACK_FRAME_RATIO_THRESHOLD, (
        f"measured {ratio:.4f} black pixels — the guard would not fire on a "
        "clip that goes black after its first second"
    )
    assert mean_luma(black_after_head) == pytest.approx(34.25, abs=1.0)


@pytest.mark.requires_hyperframes
def test_caption_raises_flowerror_on_black_output(hf_project, silence_mid, tmp_path, monkeypatch):
    """Proves the guard is WIRED, not just computed and ignored: if the black
    measurement reports an all-black render, caption() must stop the stage
    rather than hand the artifact downstream. Injected via monkeypatch per the
    brief's own permission — making HyperFrames itself produce a black render
    isn't a controlled, reliable way to test this."""
    monkeypatch.setattr("cutline.flow.black_pixel_ratio", lambda path: 1.0)
    with pytest.raises(FlowError, match="black"):
        caption(silence_mid, hf_project, tmp_path)


def test_luma_probe_reads_paths_carrying_lavfi_metacharacters(black_frame, tmp_path):
    """`take,1.mp4` is an ordinary filename; `,` ends a lavfi filter.

    The probe used to interpolate the path into `movie={path},signalstats`, so
    such a file raised "could not measure luma" — failing closed, but blaming
    the luma rather than the path. Measured, single-quoting the value is not a
    fix either: `:`, `'` and `=` still break it. The path is now an argv
    element, so there is no filtergraph to escape.
    """
    for name in ("take,1.mp4", "take'1.mp4", "take[1].mp4", "take:1.mp4", "ta ke;1.mp4"):
        awkward = tmp_path / name
        awkward.write_bytes(black_frame.read_bytes())
        assert black_pixel_ratio(awkward) == pytest.approx(1.0, abs=0.01), name
        assert mean_luma(awkward) == pytest.approx(16.0, abs=1.0), name


def test_black_pixel_ceiling_sits_between_the_floor_and_this_projects_content():
    """The ceiling is a measured separator, not a round number: the
    limited-range black floor is 16 and this project's navy content field is
    Y~28.5, so 24 sits between them. A ceiling at or below 16 could never call
    real black black; one at or above 28.5 would call the content black."""
    assert 16 < BLACK_PIXEL_LUMA_CEILING < 28


@pytest.mark.requires_hyperframes
def test_a_failing_boundary_check_raises_flowerror(monkeypatch, hf_project, silence_mid, tmp_path):
    """caption() must not hand a suspect artifact onward when verify() finds a
    violation — spec §5: "a boundary check fails → stop the flow; never hand a
    corrupted artifact to the next stage".

    cut() has had this test since Task 6; its sibling never got one, and the
    final review measured the consequence: mutating caption()'s
    `if not report.ok:` to `if False:` left the whole 54-test suite green, so
    the gate could be deleted with nothing noticing.

    As in the cut() version, a genuine violation cannot be produced from a real
    fixture — HyperFrames legitimately preserves the one property
    COMPOSITE_POLICY holds invariant — so the violation is injected and what is
    under test is caption()'s reaction to it.
    """

    def _fake_verify(before, after, policy):
        report = Report(boundary=policy.name)
        report.changes.append(Change(prop="video.codec", before="h264", after="hevc"))
        return report

    monkeypatch.setattr("cutline.flow.verify", _fake_verify)

    with pytest.raises(FlowError, match="video.codec"):
        caption(silence_mid, hf_project, tmp_path)


def test_caption_names_the_missing_tool_before_touching_the_filesystem(
    silence_mid, tmp_path, monkeypatch
):
    """A missing hyperframes used to surface as a raw FileNotFoundError out of
    subprocess — after caption() had already copied the source into the
    project's assets directory. Spec §5 wants a named failure at startup."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    project = tmp_path / "project"
    monkeypatch.setenv("PATH", str(empty))

    with pytest.raises(ToolError) as exc:
        caption(silence_mid, project, tmp_path / "out")

    assert "hyperframes" in str(exc.value)
    assert "npm install -g hyperframes" in str(exc.value)
    assert not (project / "assets" / "input.mp4").exists(), (
        "caption() copied the source before checking its tool was present"
    )


def test_a_stage_whose_binary_cannot_start_reports_the_stage(tmp_path):
    """_run() let OSError escape unwrapped, so the caller saw neither which
    stage failed nor which binary it was trying to run."""
    with pytest.raises(FlowError) as exc:
        _run(["definitely-not-a-real-binary-xyz"], "phantom stage")
    assert "phantom stage" in str(exc.value)
    assert "definitely-not-a-real-binary-xyz" in str(exc.value)
