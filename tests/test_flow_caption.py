import pytest

from cutline.flow import BLACK_FRAME_LUMA_THRESHOLD, FlowError, caption, mean_luma, run
from cutline.verify import COMPOSITE_POLICY

pytestmark = pytest.mark.requires_ffmpeg


def test_caption_stage_warns_but_does_not_fail_on_resampled_audio(
    hf_project, silence_mid, tmp_path
):
    """Measured: HyperFrames turns 44.1kHz mono into 48kHz stereo unannounced.
    That is legitimate for a re-composite and must warn, not fail."""
    result = caption(silence_mid, hf_project, tmp_path)
    assert result.report.ok
    assert any("audio" in w.prop for w in result.report.warnings)


def test_caption_stage_uses_the_composite_policy(hf_project, silence_mid, tmp_path):
    result = caption(silence_mid, hf_project, tmp_path)
    assert result.report.boundary == COMPOSITE_POLICY.name


def test_caption_output_is_not_a_black_frame(hf_project, silence_mid, tmp_path):
    """A correctly-sized black video passes every metadata assertion."""
    result = caption(silence_mid, hf_project, tmp_path)
    assert mean_luma(result.output) > BLACK_FRAME_LUMA_THRESHOLD


def test_run_executes_both_stages_in_order(hf_project, silence_mid, tmp_path):
    results = run(silence_mid, hf_project, tmp_path)
    assert [r.name for r in results] == ["cut", "caption"]


def test_mean_luma_discriminates_black_from_content(black_frame, silence_mid):
    """The guard's whole premise, checked directly and unpatched: real
    ffmpeg-black is Y~16 (limited-range floor), not 0 -- so the threshold has
    to sit above 16 without also sitting anywhere near real content. This is
    the positive control in BOTH directions: if mean_luma were mutated to
    return a constant (e.g. a large value, or 0), one of these two assertions
    goes red."""
    black = mean_luma(black_frame)
    content = mean_luma(silence_mid)

    assert black < BLACK_FRAME_LUMA_THRESHOLD, (
        f"black fixture measured {black} -- at or above the gate, "
        "so the gate could never fire on real black"
    )
    assert abs(black - 16.0) < 3.0, f"expected the limited-range floor (~16), got {black}"
    # Measured on this project's actual navy-background fixture: ~35.9, not the
    # ~200s a brighter scene would show. The margin asserted here is therefore
    # anchored to what silence_mid really measures (comfortably above the gate,
    # not an unmeasured multiplier), not to a number from a different clip.
    assert content > BLACK_FRAME_LUMA_THRESHOLD * 1.5, (
        f"real content measured {content} -- too close to the black fixture "
        "to prove the two are actually distinguishable"
    )


def test_caption_raises_flowerror_on_black_output(hf_project, silence_mid, tmp_path, monkeypatch):
    """Proves the guard is WIRED, not just computed and ignored: if mean_luma
    is broken to report a value at or under the threshold, caption() must
    stop the stage rather than hand a black artifact downstream. Injected via
    monkeypatch per the brief's own permission -- making HyperFrames itself
    produce a black render isn't a controlled, reliable way to test this."""
    monkeypatch.setattr("cutline.flow.mean_luma", lambda path: 1.0)
    with pytest.raises(FlowError, match="black"):
        caption(silence_mid, hf_project, tmp_path)
