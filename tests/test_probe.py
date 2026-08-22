import pytest

from cutline.probe import MediaInfo, probe


def test_probe_reads_geometry_and_duration(plain_av):
    info = probe(plain_av)
    assert isinstance(info, MediaInfo)
    assert info.video.width == 1920
    assert info.video.height == 1080
    assert 11.5 < info.duration < 12.5


def test_probe_captures_rotation_side_data(rotated):
    """The defect this whole project exists to catch."""
    assert abs(probe(rotated).rotation) == 90


def test_probe_reports_no_rotation_when_absent(plain_av):
    assert probe(plain_av).rotation is None


def test_probe_captures_audio_parameters(plain_av):
    a = probe(plain_av).audio
    assert a.sample_rate == 44100
    assert a.channels == 1


def test_probe_captures_per_stream_start_time(offset_streams):
    info = probe(offset_streams)
    assert abs(info.audio.start_time - info.video.start_time) > 0.2


def test_probe_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        probe(tmp_path / "nope.mp4")
