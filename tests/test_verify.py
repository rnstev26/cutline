# tests/test_verify.py
from pathlib import Path

from cutline.probe import MediaInfo, StreamInfo
from cutline.verify import COMPOSITE_POLICY, CUT_POLICY, verify


def _info(duration=12.0, width=1920, height=1080, rotation=None,
          sample_rate=44100, channels=1):
    return MediaInfo(
        path=Path("x.mp4"),
        duration=duration,
        streams=(
            StreamInfo(kind="video", codec="h264", width=width, height=height,
                       pix_fmt="yuv420p", nb_frames=360),
            StreamInfo(kind="audio", codec="aac",
                       sample_rate=sample_rate, channels=channels),
        ),
        rotation=rotation,
    )


def test_cut_boundary_accepts_a_shorter_duration():
    r = verify(_info(duration=12.0), _info(duration=9.4), CUT_POLICY)
    assert r.ok


def test_cut_boundary_rejects_lost_rotation():
    """The measured defect: rotation vanishes while everything else matches."""
    r = verify(_info(rotation=90), _info(rotation=None), CUT_POLICY)
    assert not r.ok
    assert any(c.prop == "rotation" for c in r.changes)


def test_cut_boundary_rejects_changed_geometry():
    r = verify(_info(width=1920, height=1080), _info(width=1080, height=1920), CUT_POLICY)
    assert not r.ok


def test_cut_boundary_rejects_resampled_audio():
    r = verify(_info(sample_rate=44100), _info(sample_rate=48000), CUT_POLICY)
    assert not r.ok


def test_composite_boundary_allows_rotation_to_be_consumed():
    """HyperFrames legitimately bakes rotation into a fixed canvas."""
    r = verify(_info(rotation=90), _info(rotation=None), COMPOSITE_POLICY)
    assert r.ok


def test_composite_boundary_warns_on_silent_audio_change():
    r = verify(_info(sample_rate=44100, channels=1),
               _info(sample_rate=48000, channels=2), COMPOSITE_POLICY)
    assert r.ok
    assert r.warnings


def test_report_names_the_boundary():
    assert verify(_info(), _info(), CUT_POLICY).boundary == "cut"
