import json

import pytest

from cutline.edl import EdlError, Timebase, parse_v1, parse_v3

V3 = json.dumps({
    "version": "3", "timebase": "30/1", "resolution": [1920, 1080],
    "samplerate": 44100, "layout": "mono",
    "v": [[{"src": "in.mp4", "start": 0, "dur": 97, "offset": 0, "stream": 0},
           {"src": "in.mp4", "start": 97, "dur": 103, "offset": 144, "stream": 0}]],
    "a": [[{"src": "in.mp4", "start": 0, "dur": 97, "offset": 0, "stream": 0}]],
})

V1 = json.dumps({
    "version": "1", "source": "in.mp4", "timebase": "30/1",
    "chunks": [[0, 97, 1.0], [97, 144, 99999.0], [144, 247, 1.0]],
})


def test_v3_parses_keeps_in_frames():
    edl = parse_v3(V3)
    assert len(edl.keeps) == 2
    assert edl.keeps[0].start == 0 and edl.keeps[0].dur == 97
    assert edl.keeps[1].offset == 144


def test_v3_carries_the_declared_expectation():
    edl = parse_v3(V3)
    assert edl.resolution == (1920, 1080)
    assert edl.sample_rate == 44100
    assert edl.layout == "mono"


def test_timebase_is_parsed_as_a_rational_not_assumed():
    edl = parse_v3(V3.replace('"30/1"', '"24000/1001"'))
    assert edl.timebase == Timebase(24000, 1001)
    assert edl.timebase.to_seconds(24000) == pytest.approx(1001.0)


def test_v1_keeps_are_speed_one_chunks_only():
    """`start` is the position in the OUTPUT timeline, `offset` the position in
    the SOURCE — the same convention v3 uses, so an Edl means one thing no
    matter which parser produced it."""
    edl = parse_v1(V1)
    assert len(edl.keeps) == 2
    assert edl.keeps[0].start == 0 and edl.keeps[0].offset == 0 and edl.keeps[0].dur == 97
    assert edl.keeps[1].start == 97 and edl.keeps[1].offset == 144 and edl.keeps[1].dur == 103


def test_v1_rejects_an_unsupported_speed():
    """Speed changes are legal in auto-editor and out of scope here. Silently
    treating 2.0 as a keep would misreport the output duration."""
    bad = V1.replace("1.0", "2.0", 1)
    with pytest.raises(EdlError) as exc:
        parse_v1(bad)
    assert "speed" in str(exc.value).lower()


def test_overlapping_keeps_are_rejected_naming_the_segment():
    doc = json.loads(V3)
    doc["v"][0][1]["start"] = 50  # overlaps the first keep (0..97)
    with pytest.raises(EdlError) as exc:
        parse_v3(json.dumps(doc))
    assert "50" in str(exc.value)


def test_empty_timeline_is_rejected():
    doc = json.loads(V3)
    doc["v"] = [[]]
    with pytest.raises(EdlError):
        parse_v3(json.dumps(doc))


def test_duration_seconds_uses_the_timebase():
    assert parse_v3(V3).duration_seconds == pytest.approx(200 / 30)
