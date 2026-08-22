"""Positive controls on the fixture generators themselves.

Each fixture must demonstrably contain the property it exists to exercise.
These tests use ffprobe directly rather than cutline.probe, so that a bug in
probe cannot make a broken fixture look correct.
"""

import json
import re
import subprocess


def _luma_series(path, seek=None, frames=None):
    """Per-frame YAVG via ffmpeg directly, independent of cutline.flow -- this
    must prove the FIXTURE is black on its own terms, not merely that the guard
    agrees with itself.

    The path is an argv element rather than an interpolated `movie={path}`
    lavfi source, for the same reason cutline.flow._sample_luma stopped
    interpolating it: measured, a `movie=` value breaks on `:`, `'` and `=`
    however it is quoted, and the resulting error blames the luma rather than
    the path.
    """
    head = ["-ss", str(seek)] if seek is not None else []
    tail = ["-frames:v", str(frames)] if frames is not None else []
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *head,
         "-i", str(path), *tail,
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [float(v) for v in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", proc.stdout)]


def _mean_luma(path, seek=None, frames=None):
    values = _luma_series(path, seek=seek, frames=frames)
    assert values, f"no luma samples for {path}"
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


def test_black_after_head_is_bright_at_the_head_and_black_after(black_after_head):
    """The fixture must exhibit BOTH halves of its defining property, or it
    cannot show where a luma probe sampled.

    A probe reading only the first 20 frames sees pure white here; the same
    file read whole is 11/12 black. If this fixture ever became black at the
    head too, the whole-timeline test it backs would pass for the wrong reason.
    """
    head = _mean_luma(black_after_head, frames=20)
    tail = _mean_luma(black_after_head, seek=2)
    assert head > 200, (
        f"head measured {head} -- not bright, so a head-only probe would not be fooled"
    )
    assert tail < 20, (
        f"tail measured {tail} -- not black, so a whole-file probe would have nothing to catch"
    )
