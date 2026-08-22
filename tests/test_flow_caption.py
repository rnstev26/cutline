import pytest

from cutline.flow import caption, run
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
    from cutline.flow import mean_luma

    result = caption(silence_mid, hf_project, tmp_path)
    assert mean_luma(result.output) > 5.0


def test_run_executes_both_stages_in_order(hf_project, silence_mid, tmp_path):
    results = run(silence_mid, hf_project, tmp_path)
    assert [r.name for r in results] == ["cut", "caption"]
