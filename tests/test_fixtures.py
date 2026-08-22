"""Positive controls on the fixture generators themselves.

Each fixture must demonstrably contain the property it exists to exercise.
These tests use ffprobe directly rather than cutline.probe, so that a bug in
probe cannot make a broken fixture look correct.
"""

import json
import subprocess


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


def test_offset_streams_have_divergent_start_times(offset_streams):
    data = _probe(offset_streams, ["-show_streams"])
    starts = {s["codec_type"]: float(s["start_time"]) for s in data["streams"]}
    assert abs(starts["audio"] - starts["video"]) > 0.2, (
        "streams start together — this fixture cannot exercise timeline divergence"
    )
