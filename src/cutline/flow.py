"""Orchestrate the tools and check their work at every handoff.

Nothing here implements media processing. Each stage invokes a tool, locates
what it actually produced, and verifies the artifact against the input under
that boundary's policy. A stage that cannot verify its output raises rather
than handing a suspect artifact to the next stage.
"""

from __future__ import annotations

import glob
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cutline import edl as edl_mod
from cutline.probe import MediaInfo, probe
from cutline.tools import require_auto_editor, require_hyperframes
from cutline.verify import CUT_POLICY, Report, verify

# Keeping at least this fraction of the source TIMELINE means the cut is
# effectively a no-op, and re-encoding would cost quality for nothing.
#
# "of the source TIMELINE", not "of the source's video stream", and the
# distinction is not pedantic — it was a silent-wrong-artifact bug of exactly
# the shape §2 says cutline exists to catch. The EDL's frame total counts
# TIMELINE frames at the EDL's own timebase; `MediaInfo.video.nb_frames` counts
# frames in the VIDEO STREAM. Those are the same number only when the
# container's declared duration equals the video stream's length.
#
# Measured 2026-08-23 against the old comparison, on a source carrying 6s of
# video and 12s of audio with silence at 3-5s and 8-9.5s:
#
#   EDL keep-total                    281 timeline frames (of 360) -- a real cut
#   source video stream               180 frames
#   281 >= 180 * 0.995                TRUE  -> classified a no-op
#   result                            the SOURCE was copied through byte-for-byte
#                                     UNEDITED, and the boundary reported [cut] OK
#
# (md5 of input and output identical; tests/test_flow_cut.py::
# test_a_real_cut_is_not_classified_a_no_op_when_audio_outruns_video pins it.)
#
# Comparing the EDL total against the source's timeline length in the SAME
# units removes the mismatch: 281/360 = 0.78, the cut renders.
NO_OP_RATIO = 0.995

# How often the luma probe samples. The previous implementation read
# `-read_intervals "%+#20"` -- twenty frames, i.e. the FIRST 0.67 SECONDS at
# 30fps -- and called the result the video's brightness. Measured on a clip of
# one second of white followed by five seconds of black: that sampling returns
# 235.0 and the guard does not fire; sampled across the whole timeline the same
# clip returns 52.5. Four samples per second is spread over the entire duration
# and still cheap -- measured 0.13s wall for a 12s 1080p clip (~90x realtime),
# so a 15-minute recording costs on the order of 10s. Decode dominates the
# cost, so raising or lowering this rate barely moves it.
LUMA_SAMPLE_FPS = 4

# What counts as a black PIXEL. ffmpeg measures a limited-range (tv-range) luma
# floor of 16 for literal black, not 0 -- confirmed against a real ffmpeg
# `color=c=black` clip (tests/test_fixtures.py::test_black_frame_is_actually_
# near_black pins this), so a ceiling near 0 could never fire on that floor.
# Measured on this project's fixtures the navy content field sits at Y~28.5, so
# 24 separates bar from content with roughly 8 units of headroom either side.
BLACK_PIXEL_LUMA_CEILING = 24

# What counts as a black RENDER: the fraction of sampled pixels at or below
# that ceiling. This replaces a whole-frame MEAN-luma gate, which the project's
# own spec-8 acceptance case ("rotation on a portrait source") very nearly
# failed -- measured, the captioned portrait artifact means 21.227 against a
# 20.0 gate, a 6% margin, because pillarboxing 9:16 into a 16:9 canvas fills
# 68% of every frame with Y=16 and the mean averages the bars in with the
# picture. Any portrait source darker than a synthetic navy card would have
# been rejected as "essentially black" while rendering correctly.
#
# Measured with THIS quantity instead, sampled across the whole timeline:
#
#   captioned portrait acceptance case (correct render)   0.684   passes
#   1s of white then 11s of black                         0.917   fails
#   render where only the caption overlay drew            0.980   fails
#   fully black render                                    1.000   fails
#   captioned landscape source (correct render)           0.000   passes
#
# 0.684 is not a fixture accident: it is the geometric maximum for pillarboxing
# 9:16 into 16:9 (1 - (9/16)/(16/9) = 0.6836), so it is the worst legitimate
# value this canvas can produce. The gate therefore sits 0.116 above the worst
# legitimate case (1.17x) and 0.063 below the tightest failing case it must
# still catch (the caption-only render at 0.980). A project whose canvas mixes
# more extreme aspects -- 2.35:1 letterboxed into 9:16 reaches 0.76 of bars --
# must re-measure its own population before trusting this number.
BLACK_FRAME_RATIO_THRESHOLD = 0.80


class FlowError(RuntimeError):
    """A stage failed, or produced an artifact that did not survive verification."""


@dataclass
class StageResult:
    name: str
    output: Path
    report: Report
    edl: edl_mod.Edl | None = None
    before: MediaInfo | None = None
    after: MediaInfo | None = None


def _run(argv: list[str], what: str, cwd: Path | None = None) -> None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    except OSError as exc:
        # Without this, a binary that is missing or not executable escaped as a
        # bare FileNotFoundError from subprocess, naming neither the stage nor
        # the tool — spec §5 requires the failure to name what was being run.
        raise FlowError(f"{what} could not start: {argv[0]!r} — {exc}") from exc
    if proc.returncode != 0:
        raise FlowError(f"{what} failed (exit {proc.returncode}):\n{proc.stderr.strip()}")


def cut(source: Path, out_dir: Path, margin: str = "0.2sec", edit: str = "audio") -> StageResult:
    """Cut dead air with auto-editor, export the EDL, and verify the render.

    Two auto-editor invocations: one to render, one to export the timeline. They
    are separate because `--export v3` writes the timeline INSTEAD of the video.
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"source does not exist: {source}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tool = require_auto_editor()
    before = probe(source)

    # Export the EDL FIRST so a no-op cut can be detected BEFORE paying for a
    # re-encode. Rendering first and discovering nothing was cut would have cost
    # a full generation-loss pass for no benefit.
    #
    # auto-editor overrides the extension: `-o x.json --export v3` writes `x.v3`.
    # Ask for the stem and find what it actually wrote.
    #
    # out_dir is caller-supplied and may already hold a stale `<stem>_timeline.*`
    # from a prior run — sorted() would then rank it ahead of or behind the fresh
    # export by name alone, and `produced[0]` could silently pick the wrong file.
    # Clear this stage's own glob pattern before exporting so the only match
    # left afterward is the one this call just wrote.
    #
    # glob.escape on the stem, not the raw stem: a source named `my[1].mp4`
    # turns `[1]` into a character class, so the pattern matches nothing that
    # exists. Measured: `cut()` on `my[1].mp4` raised "auto-editor wrote no EDL
    # matching .../my[1]_timeline.*" while `my[1]_timeline.v3` sat right there,
    # and the stale-EDL pre-clean above silently swept nothing for the same
    # reason. auto-editor itself handles the name fine — the bug was ours.
    edl_glob = f"{glob.escape(source.stem)}_timeline.*"
    for stale in out_dir.glob(edl_glob):
        stale.unlink()
    edl_stem = out_dir / f"{source.stem}_timeline"
    _run(
        [
            str(tool.path), str(source),
            "--edit", edit,
            "--margin", margin,
            "--export", "v3",
            "-o", str(edl_stem),
        ],
        "auto-editor EDL export",
    )
    produced = sorted(out_dir.glob(edl_glob))
    if not produced:
        raise FlowError(f"auto-editor wrote no EDL matching {edl_stem}.*")
    if len(produced) > 1:
        raise FlowError(
            f"ambiguous EDL export: multiple files matched {edl_stem}.* -> {produced}"
        )
    parsed = edl_mod.parse(produced[0])
    source_frames = _source_timeline_frames(before, parsed)
    _check_edl_fits_the_source(parsed, source_frames, source)

    # No-op short-circuit: if the cut would keep essentially everything, copy
    # instead of re-encoding. A re-encode for a ~0% cut is pure generation loss.
    if source_frames and parsed.total_frames >= source_frames * NO_OP_RATIO:
        rendered = out_dir / f"{source.stem}_cut.mp4"
        shutil.copyfile(source, rendered)
        after = probe(rendered)
        # §5's rule is "a boundary check fails -> stop the flow", stated without
        # exception; this path used to return its report WITHOUT gating on it,
        # so a failing report here would have printed and exited zero. Harmless
        # while the path is a byte-for-byte copy — the report cannot fail — but
        # an unstated exception is how a reachable one gets added later.
        report = verify(before, after, CUT_POLICY)
        if not report.ok:
            raise FlowError(
                "cut stage short-circuited as a no-op and the copy still did not "
                f"survive verification (this should be impossible for a byte-for-byte "
                f"copy, so treat it as a bug in the copy path):\n{report}"
            )
        return StageResult(
            name="cut",
            output=rendered,
            report=report,
            edl=parsed,
            before=before,
            after=after,
        )

    rendered = out_dir / f"{source.stem}_cut.mp4"
    _run(
        [
            str(tool.path), str(source),
            "--edit", edit,
            "--margin", margin,
            *_profile_args(before),
            "-o", str(rendered),
        ],
        "auto-editor render",
    )
    if not rendered.exists():
        raise FlowError(f"auto-editor reported success but {rendered} does not exist")

    after = probe(rendered)
    _check_render_matches_edl(parsed, after, rendered)
    report = verify(before, after, CUT_POLICY)
    if not report.ok:
        raise FlowError(f"cut stage did not survive verification:\n{report}")

    return StageResult(
        name="cut", output=rendered, report=report, edl=parsed, before=before, after=after
    )


# ffprobe's H.264 profile names, mapped to the vocabulary auto-editor's
# `-profile:v` accepts ("For h264: high, main, or baseline"). Only H.264 is
# mapped, and deliberately: measured, an HEVC source came back HEVC/Main
# unasked, so nothing needs declaring there, and `-profile:v main` would be the
# wrong vocabulary if it did.
_H264_PROFILE_ARG = {
    "baseline": "baseline",
    "constrained baseline": "baseline",
    "main": "main",
    "high": "high",
}


def _profile_args(before: MediaInfo) -> list[str]:
    """Declare the source's video profile to the renderer, rather than hoping.

    §4.1 makes `video.profile` an invariant of the cut boundary — "catches
    silent transcode changes". Measured 2026-08-23 on a real Apple-written
    `.mov` (H.264 **Main**), auto-editor 31.5.0 rendered H.264 **High**: its
    libx264 defaults, not the source's profile. The boundary check fired, on a
    healthy render, and the cut was refused:

        [cut] FAILED
          violation: video.profile: 'Main' -> 'High'

    Two ways to make that stop. Drop `profile` from the invariant set — which
    is deleting the check §4.1 says catches silent transcode changes. Or make
    the render satisfy it, which auto-editor exposes an argument for. Measured
    with `-profile:v main` on the same file: profile Main, frame count 1151
    unchanged from the run without it.

    So the invariant is not weakened; the renderer is simply told what it is
    expected to preserve. This is the EDL-as-declared-expectation idea (§3.1)
    running in the one direction v1 actually has a channel for.

    Returns [] when the profile is absent or outside the mapped vocabulary. That
    is not an exemption: `verify()` still compares the property afterwards, so
    an unmapped profile that the renderer changes still fails the boundary.
    """
    video = before.video
    if video is None or video.codec != "h264" or not video.profile:
        return []
    arg = _H264_PROFILE_ARG.get(video.profile.strip().lower())
    return ["-profile:v", arg] if arg else []


def _source_timeline_frames(before: MediaInfo, parsed: edl_mod.Edl) -> int | None:
    """The source's length in the EDL's OWN units: timeline frames.

    auto-editor builds its timeline from the source's declared duration at the
    timebase it chose, so this is the quantity its keep-totals are counted in.
    Measured 2026-08-23 on six containers, this predicted auto-editor's
    no-cut render length EXACTLY in every case:

        container                     format.duration   predicted   rendered
        ts.mov            (normal)           3.000000          90         90
        ts_frag.mov       (fragmented)       3.066667          92         92
        nobf_frag.mov     (fragmented)       3.023242          91         91
        qtnormal.mkv      (matroska)         3.023000          91         91
        qs.mov            (normal)          12.000000         360        360
        qs_frag.mov       (fragmented)      12.066667         362        362

    Rounded to 1e-3 of a frame before the ceiling: ffprobe reports duration to
    six decimals, so 3.066667 * 30 arrives as 92.00001 and a bare ceil() would
    read 93. Rounding at a thousandth of a frame is far below any real
    quantity here and far above the reporting noise.

    Returns None when the duration is unreadable — fail closed, and every
    caller treats None as "cannot judge" rather than as a permissive default.
    """
    if before.duration <= 0:
        return None
    tb = parsed.timebase
    raw = before.duration * tb.num / tb.den
    return math.ceil(round(raw, 3))


def _check_edl_fits_the_source(
    parsed: edl_mod.Edl, source_frames: int | None, source: Path
) -> None:
    """The one source-dependent EDL invariant. `edl.parse` stays pure.

    `edl._validate` enforces ordering, positivity and non-overlap — every one a
    property of the keep-list considered ALONE. None of them is bounded by the
    source, because a pure parser has no source to be bounded by. So an EDL
    claiming a segment past the end of the footage parsed clean, validated
    clean, and reached the render: measured, a v3 timeline declaring a single
    999999-frame keep against a 90-frame source raised nothing.

    That gap mattered because the only quantitative gate downstream
    (`_check_render_matches_edl`) compares the render against THAT SAME EDL —
    so an EDL that over-claims and a render that pads to match it AGREE, and
    the boundary reports OK.

    Validation is therefore parse-pure PLUS this one check, which needs the
    source's measured length and so cannot live in the parser.

    Fails closed: an unmeasurable source length refuses rather than skips.
    """
    if source_frames is None:
        raise FlowError(
            f"cannot bound auto-editor's EDL against {source}: the source's "
            "duration is unreadable, so a keep-list claiming frames the source "
            "does not have could not be detected. Refusing to render."
        )
    for keep in parsed.keeps:
        end = keep.offset + keep.dur
        if end > source_frames:
            raise FlowError(
                f"auto-editor's EDL claims source frames [{keep.offset}, {end}) but "
                f"{source} carries only {source_frames} timeline frames at "
                f"{parsed.timebase.num}/{parsed.timebase.den}. A keep-segment past "
                "the end of the footage would be padded by the renderer and the "
                "render/EDL agreement check would then agree with itself."
            )
    if parsed.total_frames > source_frames:
        raise FlowError(
            f"auto-editor's EDL keeps {parsed.total_frames} frames but {source} "
            f"carries only {source_frames} timeline frames at "
            f"{parsed.timebase.num}/{parsed.timebase.den}."
        )


def _check_render_matches_edl(parsed: edl_mod.Edl, after: MediaInfo, rendered: Path) -> None:
    """Bound the shrink against auto-editor's own declaration.

    CUT_POLICY cannot catch truncation by itself and should not try to: duration
    and frame count are legitimately allowed to shrink at this boundary, so an
    artifact holding 0.4 seconds of a 12-second source is "a shrink" and the
    boundary report reads `[cut] OK`. What bounds the shrink is the EDL —
    auto-editor declared a keep-list before rendering, and the render either
    carries that many frames or it does not. §4.1 names frame count as the
    property that "catches truncation"; this is the check that lets it.

    Measured across all six fixture classes (silence_mid, silence_at_zero,
    silence_to_eof, no_silence, offset_streams, rotated_with_silence) against
    auto-editor 31.5.0: the rendered frame count equals the EDL total EXACTLY —
    delta 0 in every case. So this is an equality, not a tolerance. A tolerance
    would be an unmeasured knob, and the auto-editor version is pinned; if a
    real source ever produces a ±1 delta, that is a measurement to take, not a
    slack to guess.

    Fails closed: an unreadable frame count is not evidence the render is sound.
    """
    declared = parsed.total_frames
    actual = after.video.nb_frames if after.video else None
    if actual is None:
        raise FlowError(
            f"cannot verify {rendered} against its EDL: the render reports no frame "
            f"count, so auto-editor's declared {declared}-frame keep-list cannot be "
            "checked. Refusing to call this cut verified."
        )
    if actual != declared:
        raise FlowError(
            f"cut stage rendered {actual} frames but its own EDL declared {declared} "
            f"({rendered}). auto-editor's keep-list and its render disagree — the "
            "artifact is truncated or padded."
        )


_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")
_PBLACK_RE = re.compile(r"lavfi\.blackframe\.pblack=([0-9.]+)")


@dataclass(frozen=True)
class LumaSample:
    """What one sampling pass over a file measured."""

    mean: float         # mean per-frame YAVG across the sampled frames
    black_ratio: float  # mean per-frame fraction of pixels at/below the ceiling
    frames: int


def _sample_luma(path: Path) -> LumaSample:
    """Sample brightness across the WHOLE timeline, in one decode pass.

    The path is passed as an ordinary `-i` argument rather than interpolated
    into a `movie=` lavfi source. That is not merely tidier: the old form broke
    on ordinary filenames. Measured, single-quoting a `movie=` path survives
    `,` `[` `]` `;` `\\` and spaces but still fails on `:`, `'` and `=` -- so a
    file called `take,1.mp4` raised "could not measure luma", blaming the luma
    rather than the path, and `take:1.mp4` and `take'1.mp4` failed the same way
    however they were quoted. Handing ffmpeg the filename as an argv element
    removes the escaping problem instead of trying to win it.
    """
    path = Path(path)
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
         "-i", str(path),
         "-vf", (f"fps={LUMA_SAMPLE_FPS},signalstats,"
                 f"blackframe=amount=0:threshold={BLACK_PIXEL_LUMA_CEILING},"
                 "metadata=print:file=-"),
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    yavg = [float(v) for v in _YAVG_RE.findall(proc.stdout)]
    pblack = [float(v) for v in _PBLACK_RE.findall(proc.stdout)]
    if not yavg or len(pblack) != len(yavg):
        raise FlowError(
            f"could not measure luma for {path} "
            f"({len(yavg)} luma samples, {len(pblack)} black-pixel samples; "
            f"ffmpeg said: {proc.stderr.strip()[:200] or 'nothing'})"
        )
    return LumaSample(
        mean=sum(yavg) / len(yavg),
        black_ratio=sum(pblack) / len(pblack) / 100.0,
        frames=len(yavg),
    )


def mean_luma(path: Path) -> float:
    """Average brightness across the whole timeline.

    Diagnostic rather than gate: a correctly-sized, correctly-encoded black
    video satisfies every metadata assertion, but so does a correctly rendered
    portrait source whose pillarbox bars drag the mean down. `black_pixel_ratio`
    is what the caption stage actually gates on; this number goes in the message
    so a human can see how dark the render was as well as how much of it was
    black.
    """
    return _sample_luma(path).mean


def black_pixel_ratio(path: Path) -> float:
    """Fraction of sampled pixels sitting at or below the black floor.

    The 'is there actually a picture here' check. Unlike a whole-frame mean this
    separates "the render is black" from "the render is correct and letterboxed"
    -- see BLACK_FRAME_RATIO_THRESHOLD for the measured populations.
    """
    return _sample_luma(path).black_ratio


def caption(source: Path, project_dir: Path, out_dir: Path) -> StageResult:
    """Composite captions over `source` using a HyperFrames project.

    HyperFrames is a re-composite: it consumes rotation into its canvas, takes
    the composition's duration, and resamples audio. COMPOSITE_POLICY treats
    those as warnings. A missing artifact or a black frame is a failure.
    """
    from cutline.verify import COMPOSITE_POLICY

    # Resolve and pin BEFORE touching the filesystem: spec §5 wants a missing
    # tool to fail at startup naming the tool, not part-way through after the
    # source has already been copied into the project's assets directory.
    tool = require_hyperframes()

    source, project_dir, out_dir = Path(source), Path(project_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = project_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, assets / "input.mp4")

    before = probe(source)
    renders = project_dir / "renders"
    existing = set(renders.glob("*.mp4")) if renders.exists() else set()
    # `hyperframes render` resolves its default output path (renders/<name>.mp4)
    # against the PROCESS cwd, not the DIR argument it was given — measured: run
    # from elsewhere with the project passed positionally, it still wrote into
    # <cwd>/renders/, not <project_dir>/renders/. Set cwd explicitly so the
    # render lands where `renders` above expects to find it.
    _run([str(tool.path), "render"], "hyperframes render", cwd=project_dir)

    new = sorted(set(renders.glob("*.mp4")) - existing) if renders.exists() else []
    if not new:
        raise FlowError(f"hyperframes reported success but wrote no new mp4 in {renders}")
    if len(new) > 1:
        raise FlowError(
            f"ambiguous render: multiple new files appeared in {renders} -> {new}"
        )
    produced = new[0]
    final = out_dir / f"{source.stem}_captioned.mp4"
    shutil.copyfile(produced, final)

    after = probe(final)
    report = verify(before, after, COMPOSITE_POLICY)
    if not report.ok:
        raise FlowError(f"caption stage did not survive verification:\n{report}")
    black = black_pixel_ratio(final)
    if black >= BLACK_FRAME_RATIO_THRESHOLD:
        raise FlowError(
            f"caption stage produced an essentially black video: {final} "
            f"({black:.1%} of sampled pixels at or below luma "
            f"{BLACK_PIXEL_LUMA_CEILING}, mean luma {mean_luma(final):.1f})"
        )

    return StageResult(name="caption", output=final, report=report,
                       before=before, after=after)


def run(source: Path, project_dir: Path, out_dir: Path) -> list[StageResult]:
    """The v1 flow: cut, verify, caption, verify.

    Spec 5, interrupt policy: on failure or interruption the last VERIFIED
    artifact stays on disk and the error names the stage that completed, so a
    long run is resumable rather than lost. Stages are therefore accumulated as
    they succeed, not collected at the end.
    """
    done: list[StageResult] = []
    try:
        done.append(cut(source, out_dir))
        done.append(caption(done[-1].output, project_dir, out_dir))
    except (FlowError, KeyboardInterrupt) as exc:
        completed = ", ".join(r.name for r in done) or "none"
        last = done[-1].output if done else source
        raise FlowError(
            f"flow stopped during stage {len(done) + 1}. Completed: {completed}. "
            f"Last verified artifact: {last}. Cause: {exc}"
        ) from exc
    return done
