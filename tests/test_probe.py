import shutil
import subprocess
from pathlib import Path

import pytest

from cutline.probe import MediaInfo, _count_video_packets, probe


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


@pytest.mark.requires_ffmpeg
def test_packet_count_agrees_with_the_header_frame_count(
    plain_av, rotated, black_frame, variable_frame_rate, silence_mid
):
    """The standing control on `probe`'s fallback measurement.

    `_count_video_packets` counts PACKETS and reports them as a frame count.
    That identity holds for one coded frame per packet, which is every codec
    and container in this project — but it is an assumption, and an assumption
    nothing checks is how a silently wrong number gets into a directional
    comparison. Measured 2026-08-23 across seven files (these five plus a
    fragmented `.mov` and a real Apple-written VFR capture), header `nb_frames`,
    `-count_packets` and `-count_frames` returned the SAME integer in 7 of 7.

    This test re-proves it on every run against the files that HAVE a header
    count, so a future codec or ffmpeg that breaks the identity is caught here
    rather than inside a boundary report.
    """
    for path in (plain_av, rotated, black_frame, variable_frame_rate, silence_mid):
        header = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip().rstrip(",")
        packets = _count_video_packets(Path(shutil.which("ffprobe")), Path(path))
        assert header.isdigit(), f"{path} has no header count to control against"
        assert packets == int(header), f"{path}: packets {packets} != header {header}"


@pytest.mark.requires_ffmpeg
def test_frame_count_is_measured_when_the_container_omits_it(
    fragmented_source, silence_mid
):
    """A container with no header frame count must still yield a number.

    Before this, `probe()` returned None and `flow.cut()` compared None against
    the render's count under a "may shrink, not grow" rule. `_grew` fails closed
    on an unreadable side — correctly — so a healthy recording was refused for
    a quantity nobody had measured. The fix measures it; it does not exempt it.

    The count is asserted EQUAL to the normally-muxed twin's, not merely
    non-None: the fragmented file is a `-c copy` remux of the same coded video,
    so any other answer means the fallback is measuring the wrong thing.
    """
    frag, normal = probe(fragmented_source), probe(silence_mid)
    assert frag.video.nb_frames == normal.video.nb_frames
    assert frag.video.nb_frames is not None


@pytest.mark.requires_ffmpeg
def test_probe_counts_streams_by_kind(plain_av):
    """§4.1's "stream count + kinds" row, as something the model can address."""
    info = probe(plain_av)
    assert (info.video_streams, info.audio_streams) == (1, 1)
