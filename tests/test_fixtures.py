"""Positive controls on the fixture generators themselves.

Each fixture must demonstrably contain the property it exists to exercise.
These tests use ffprobe directly rather than cutline.probe, so that a bug in
probe cannot make a broken fixture look correct.
"""

import json
import re
import subprocess


def _mean_luma(path):
    """Average brightness via ffprobe directly, independent of
    cutline.flow.mean_luma -- this must prove the FIXTURE is black on its own
    terms, not merely that the guard agrees with itself."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-f", "lavfi",
         "-i", f"movie={path},signalstats",
         "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
         "-of", "csv=p=0", "-read_intervals", "%+#20"],
        capture_output=True, text=True,
    )
    values = [float(v) for v in re.split(r"[,\s]+", proc.stdout) if v.strip()]
    return sum(values) / len(values)


def _probe(path, args):
    out = subprocess.run(
        ["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _silences(path):
    """Silence spans ffmpeg reports, as (start, end) float pairs."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-vn", "-i", str(path),
         "-af", "silencedetect=n=-30dB:d=0.3", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts, ends = [], []
    for line in proc.stderr.splitlines():
        if "silence_start:" in line:
            starts.append(float(line.split("silence_start:")[1].strip()))
        if "silence_end:" in line:
            ends.append(float(line.split("silence_end:")[1].split("|")[0].strip()))
    return list(zip(starts, ends, strict=False))


def test_rotated_actually_carries_rotation(rotated):
    data = _probe(rotated, ["-select_streams", "v:0", "-show_streams"])
    side = data["streams"][0].get("side_data_list", [])
    rotations = [s.get("rotation") for s in side if "rotation" in s]
    assert rotations, "fixture carries NO rotation side data — it cannot test the defect"
    assert abs(rotations[0]) == 90


def test_no_silence_really_has_none(no_silence):
    assert _silences(no_silence) == [], "negative control is contaminated"


def test_silence_mid_has_silence(silence_mid):
    spans = _silences(silence_mid)
    assert spans, "positive control found no silence — the detector or fixture is broken"


def test_silence_at_zero_starts_at_zero(silence_at_zero):
    spans = _silences(silence_at_zero)
    assert spans and spans[0][0] < 0.05


def test_silence_to_eof_ends_at_or_past_duration(silence_to_eof):
    dur = float(_probe(silence_to_eof, ["-show_format"])["format"]["duration"])
    spans = _silences(silence_to_eof)
    assert spans, "no silence detected in the to-EOF fixture"
    assert spans[-1][1] >= dur - 0.05


def test_rotated_with_silence_carries_both_rotation_and_silence(rotated_with_silence):
    data = _probe(rotated_with_silence, ["-select_streams", "v:0", "-show_streams"])
    side = data["streams"][0].get("side_data_list", [])
    rotations = [s.get("rotation") for s in side if "rotation" in s]
    assert rotations, "fixture carries NO rotation side data — it cannot test the defect"
    assert abs(rotations[0]) == 90

    spans = _silences(rotated_with_silence)
    assert spans, (
        "no silence detected — a cut through this fixture would short-circuit "
        "as a no-op and never exercise auto-editor's render path"
    )


def test_black_frame_is_actually_near_black(black_frame):
    """A correctly-sized, correctly-encoded black video does NOT measure 0 --
    limited-range (tv-range) YUV floors literal black at Y=16. If this fixture
    ever measured near 0 or near real-content brightness, it could not
    exercise the guard's actual decision boundary."""
    luma = _mean_luma(black_frame)
    assert luma < 20.0, f"fixture measured {luma} -- not black enough to test the guard"
    assert abs(luma - 16.0) < 3.0, f"expected the limited-range black floor (~16), got {luma}"


def test_offset_streams_have_divergent_start_times(offset_streams):
    data = _probe(offset_streams, ["-show_streams"])
    starts = {s["codec_type"]: float(s["start_time"]) for s in data["streams"]}
    assert abs(starts["audio"] - starts["video"]) > 0.2, (
        "streams start together — this fixture cannot exercise timeline divergence"
    )
