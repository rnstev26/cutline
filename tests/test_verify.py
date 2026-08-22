# tests/test_verify.py
from pathlib import Path

import pytest

from cutline.probe import MediaInfo, StreamInfo
from cutline.verify import (
    CHECKED_PROPERTIES,
    COMPOSITE_POLICY,
    CUT_POLICY,
    Policy,
    verify,
)


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


def test_cut_boundary_distinguishes_none_from_zero_rotation():
    """None (absent) and 0 (explicit no-rotation) are different facts.

    A naive `or 0` coercion anywhere in the chain would silently collapse
    them; this locks in that `_get`/`verify` never do that.
    """
    r = verify(_info(rotation=None), _info(rotation=0), CUT_POLICY)
    assert not r.ok
    change = next(c for c in r.changes if c.prop == "rotation")
    assert change.before is None
    assert change.after == 0


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


def _info_without_audio(duration=12.0):
    """A MediaInfo with no audio stream at all — distinct from a present-but-silent one."""
    return MediaInfo(
        path=Path("x.mp4"),
        duration=duration,
        streams=(
            StreamInfo(kind="video", codec="h264", width=1920, height=1080,
                       pix_fmt="yuv420p", nb_frames=360),
        ),
        rotation=None,
    )


def test_cut_boundary_rejects_stream_absence():
    """Comparing a file WITH audio against one WITHOUT: `.audio` is None on the
    after side, so `_get` returns None for every audio.* prop via its
    `stream is None` branch — reported as violations under CUT_POLICY.
    """
    r = verify(_info(), _info_without_audio(), CUT_POLICY)
    assert not r.ok
    changed_props = {c.prop for c in r.changes}
    assert {"audio.sample_rate", "audio.channels", "audio.codec"} <= changed_props
    for c in r.changes:
        if c.prop.startswith("audio."):
            assert c.after is None


def test_composite_boundary_warns_on_stream_absence():
    """The same audio-stream-absence, but under COMPOSITE_POLICY where those
    audio props are `warn`, not `invariant` — it should not fail .ok.
    """
    r = verify(_info(), _info_without_audio(), COMPOSITE_POLICY)
    assert r.ok
    warned_props = {w.prop for w in r.warnings}
    assert {"audio.sample_rate", "audio.channels", "audio.codec"} <= warned_props


# --- may_change is load-bearing -------------------------------------------
#
# Before this, `Policy.may_change` was assigned in three places and read
# nowhere: `_all_props()` returned `invariant | warn`, so every property a
# policy called "may change" — duration, frame count and both start_times at
# the cut boundary — was not examined at all.


def test_cut_boundary_rejects_a_duration_that_grew():
    """§4.1 says duration "may shrink" at the cut boundary. It does not say
    "may change". A cut that produced a LONGER artifact than its source is a
    defect, and until may_change was read this reported OK."""
    r = verify(_info(duration=9.4), _info(duration=12.0), CUT_POLICY)
    assert not r.ok
    change = next(c for c in r.changes if c.prop == "duration")
    assert "shrink" in change.note


def test_cut_boundary_rejects_a_frame_count_that_grew():
    before = _info()
    after = MediaInfo(
        path=Path("x.mp4"), duration=12.0, rotation=None,
        streams=(
            StreamInfo(kind="video", codec="h264", width=1920, height=1080,
                       pix_fmt="yuv420p", nb_frames=400),
            StreamInfo(kind="audio", codec="aac", sample_rate=44100, channels=1),
        ),
    )
    r = verify(before, after, CUT_POLICY)
    assert not r.ok
    assert any(c.prop == "video.nb_frames" for c in r.changes)


def test_a_may_shrink_property_that_cannot_be_read_fails_closed():
    """An unreadable frame count is not evidence the shrink was legitimate.

    ffprobe does not report nb_frames for every container. When it does not,
    the direction cannot be established — so the change is reported rather than
    waved through."""
    before = _info()
    after = MediaInfo(
        path=Path("x.mp4"), duration=9.4, rotation=None,
        streams=(
            StreamInfo(kind="video", codec="h264", width=1920, height=1080,
                       pix_fmt="yuv420p", nb_frames=None),
            StreamInfo(kind="audio", codec="aac", sample_rate=44100, channels=1),
        ),
    )
    r = verify(before, after, CUT_POLICY)
    assert not r.ok
    assert any(c.prop == "video.nb_frames" for c in r.changes)


def test_composite_boundary_lets_duration_grow():
    """The direction constraint is per-boundary, not global: §4.1 says the
    composite's duration becomes the COMPOSITION's, which may be longer."""
    r = verify(_info(duration=9.4), _info(duration=12.0), COMPOSITE_POLICY)
    assert r.ok


def test_a_policy_that_leaves_a_property_unclassified_is_rejected():
    """The exhaustiveness rule, which is what keeps `may_change` honest: a
    property in neither bucket is one the boundary never looks at, and that
    must be impossible to express by accident."""
    with pytest.raises(ValueError, match="does not classify"):
        Policy(name="holey", invariant=frozenset(CHECKED_PROPERTIES - {"video.nb_frames"}))


def test_a_policy_that_double_classifies_a_property_is_rejected():
    with pytest.raises(ValueError, match="appears in both"):
        Policy(
            name="ambiguous",
            invariant=frozenset(CHECKED_PROPERTIES),
            may_change=frozenset(["duration"]),
        )


def test_a_policy_naming_a_property_verify_cannot_read_is_rejected():
    with pytest.raises(ValueError, match="not in CHECKED_PROPERTIES"):
        Policy(name="fanciful", invariant=frozenset(CHECKED_PROPERTIES | {"video.bitrate"}))


def test_may_shrink_must_be_a_subset_of_may_change():
    with pytest.raises(ValueError, match="may_shrink"):
        Policy(
            name="confused",
            invariant=frozenset(CHECKED_PROPERTIES),
            may_shrink=frozenset(["duration"]),
        )


def test_both_shipped_policies_classify_every_checked_property():
    """Reads the partition rather than trusting the constructor ran: if either
    policy were ever built by derivation from CHECKED_PROPERTIES, __post_init__
    would pass by construction and prove nothing."""
    for policy in (CUT_POLICY, COMPOSITE_POLICY):
        assert policy.invariant | policy.may_change | policy.warn == CHECKED_PROPERTIES
        assert policy.may_shrink <= policy.may_change


def test_checked_properties_covers_the_section_4_1_set():
    """§4.1's table, as scalars verify() can address. Frame count and the two
    start_times are the ones that were silently unexamined."""
    assert {
        "duration", "rotation",
        "video.nb_frames", "video.codec", "video.profile", "video.pix_fmt",
        "video.width", "video.height", "video.sar", "video.dar",
        "video.start_time",
        "audio.sample_rate", "audio.channels", "audio.codec", "audio.start_time",
    } == set(CHECKED_PROPERTIES)
