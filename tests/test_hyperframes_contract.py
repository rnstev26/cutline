"""One test per assumption `flow.caption()` (and `tests/conftest.py`'s
`hf_project` fixture) makes about the installed `hyperframes` CLI's SHAPE --
not its version.

`tools.HYPERFRAMES_SERIES` pins a version number, but the version number is a
PROXY: what actually breaks cutline is a change in the shape it depends on.
Measured from flow.caption() and hf_project, that shape is six things:

  1. `hyperframes render` exists as an invocable subcommand.
  2. Its default output path (`renders/<name>.mp4`) resolves against the
     PROCESS CWD, not the `DIR` argument it was given.
  3. `assets/input.mp4` is where the composition reads its video source.
  4. `hyperframes.json`'s `paths.blocks` / `paths.assets` keys name a real
     configuration surface.
  5. The composition attribute vocabulary -- `data-composition-id`,
     `data-start`, `data-duration`, `data-width`, `data-height`,
     `class="clip"` -- actually drives the render.
  6. `data-no-timeline` skips the ~45s sub-composition-readiness poll.

`tests/test_flow_caption.py` already exercises all six IMPLICITLY, by running
a real render. Its diagnostic when something moves is "hyperframes reported
success but wrote no new mp4" -- true, but silent about WHICH assumption
moved. Each test below isolates one, so a future reader learns what changed
rather than merely that the render failed.

Every project scaffold here is built fresh, per test, by `_scaffold()` below
-- deliberately NOT `conftest.py`'s session-scoped `hf_project` fixture, which
several of these tests need to deliberately break (missing asset, mismatched
paths, no `data-no-timeline`) in ways that would leak into every other test
sharing that fixture.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from cutline.probe import probe
from cutline.tools import require_hyperframes

pytestmark = [pytest.mark.requires_ffmpeg, pytest.mark.requires_hyperframes]


def _scaffold(
    project_dir: Path,
    source_video: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    duration: int = 6,
    no_timeline: bool = True,
    video_dir: str = "assets",
    video_src: str = "assets/input.mp4",
    hyperframes_paths_assets: str | None = "assets",
    write_hyperframes_json: bool = True,
) -> Path:
    """Build a minimal, disposable HyperFrames project under `project_dir`.

    Mirrors the shape `hf_project` scaffolds (same attribute vocabulary, same
    `assets/input.mp4` convention) but every dimension of it is a parameter,
    so each test below can move exactly one axis and hold the rest at the
    fixture's real values.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    media_dir = project_dir / video_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "input.mp4").write_bytes(Path(source_video).read_bytes())

    if write_hyperframes_json:
        assets_path = hyperframes_paths_assets or "assets"
        (project_dir / "hyperframes.json").write_text(
            json.dumps({"paths": {"blocks": "compositions", "assets": assets_path}}) + "\n"
        )

    no_timeline_attr = " data-no-timeline" if no_timeline else ""
    (project_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width={width}, height={height}" />
<style>*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{width}px;height:{height}px;overflow:hidden;background:#000}}
#footage{{position:absolute;inset:0}}
#footage video{{width:100%;height:100%;object-fit:contain}}</style></head>
<body><div id="root" data-composition-id="main"{no_timeline_attr} data-start="0"
data-duration="{duration}" data-width="{width}" data-height="{height}">
<div id="footage" class="clip" data-start="0" data-duration="{duration}" data-track-index="0">
<video id="v1" src="{video_src}" data-media data-start="0" data-duration="{duration}" muted></video>
</div>
</div></body></html>
""")
    return project_dir


def _renders(project_dir: Path) -> list[Path]:
    d = project_dir / "renders"
    return sorted(d.glob("*.mp4")) if d.exists() else []


def test_render_subcommand_is_invocable():
    """Assumption 1: `hyperframes render` exists as an invocable subcommand.

    Cheap and independent of every other assumption: asks the CLI's own
    `--help`, not a real render. If upstream ever renames or removes
    `render`, THIS fails first, naming exactly that, before any of the
    slower render-based tests below even get a chance to run and blame
    something else.

    Checking the exit code and the word "render" alone is NOT enough --
    measured directly: `hyperframes <unknown-subcommand> --help` does not
    error, it falls back to the top-level command listing (exit 0), and
    that listing names `render` too, among many other subcommands. A first
    draft of this test asserted exactly that and stayed green against a
    deliberately misspelled subcommand name. The assertion below instead
    checks for `render`'s OWN help text -- the default output path it
    documents (`renders/<name>.mp4`, the same path flow.caption() locates
    its output by) -- which only appears when the CLI actually resolved
    `render` as a real subcommand.
    """
    tool = require_hyperframes()
    proc = subprocess.run(
        [str(tool.path), "render", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, (
        f"`hyperframes render --help` exited {proc.returncode} -- the "
        "`render` subcommand cutline shells out to in flow.caption() may "
        f"have been renamed or removed upstream.\nstderr: {proc.stderr}"
    )
    assert "renders/<name>.mp4" in proc.stdout, (
        "`hyperframes render --help` exited 0, but its output no longer "
        "documents the default output path (renders/<name>.mp4) that "
        "flow.caption() relies on to locate what it rendered. Either "
        "`render` was not recognized as a real subcommand (the CLI falls "
        "back to its top-level listing on an unknown one, silently, exit "
        "0) or the default output path convention itself moved."
    )


def test_render_output_path_resolves_against_process_cwd_not_the_dir_argument(
    tmp_path, plain_av
):
    """Assumption 2 -- the subtle one, and the most likely to be silently
    "fixed" upstream: the OUTPUT PATH `hyperframes render` writes to (default
    `renders/<name>.mp4`) resolves against the process's CWD, not the `DIR`
    argument it was told to render.

    flow.caption() works around this by passing `cwd=project_dir` to
    subprocess.run rather than trusting `hyperframes render <project_dir>` to
    write inside that directory from wherever cutline happens to be running.

    If this test ever FAILS -- i.e. the render lands under
    `<project_dir>/renders/` instead of `<elsewhere>/renders/` -- that is
    GOOD NEWS: upstream fixed the quirk, and flow.caption()'s
    `cwd=project_dir` workaround (see the comment above its `_run(...)` call)
    can be simplified. It is a green light for a code change, not a
    regression to `git revert`.
    """
    project_dir = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _scaffold(project_dir, plain_av)

    tool = require_hyperframes()
    proc = subprocess.run(
        [str(tool.path), "render", str(project_dir)],
        capture_output=True, text=True, timeout=60, cwd=elsewhere,
    )
    assert proc.returncode == 0, f"render failed outright: {proc.stderr}\n{proc.stdout}"

    cwd_renders = _renders(elsewhere)
    project_renders = _renders(project_dir)

    assert cwd_renders, (
        "expected hyperframes render's default output path to land under the "
        f"PROCESS CWD ({elsewhere}/renders/) -- nothing rendered there at "
        "all, so this measurement itself needs re-taking before trusting "
        "either half of this test."
    )
    assert not project_renders, (
        "hyperframes render wrote its output under the DIR ARGUMENT "
        f"({project_dir}/renders/) instead of the process cwd. This is GOOD "
        "NEWS, not a regression: upstream appears to have fixed the cwd "
        "quirk this test pins. flow.caption()'s `cwd=project_dir` "
        "workaround (see the _run(..., cwd=project_dir) call in flow.py) is "
        "no longer needed and should be simplified to pass project_dir "
        "positionally instead."
    )


def test_composition_reads_assets_input_mp4_as_its_video_source(tmp_path, plain_av):
    """Assumption 3: the composition's `<video src="assets/input.mp4">` is
    actually read from that literal, project-root-relative path -- not
    decoration flow.caption() copies to for no functional reason.

    Measured directly: with the file present the render succeeds; with it
    removed, hyperframes' own frame extractor logs
    `WARNING: video src="assets/input.mp4" could not be resolved on disk`
    and then REFUSES to ship a render at all (a `coverage 0.0%` gate below
    its correctness threshold) -- it does not silently degrade to a still
    frame the way the warning wording alone might suggest. That refusal
    (non-zero exit) is the signal asserted below: if hyperframes.json's own
    source of asset truth ever moves, this must go red HERE, naming the
    missing file, rather than surfacing three layers up as flow.caption()'s
    generic "wrote no new mp4".
    """
    project_dir = tmp_path / "project"
    _scaffold(project_dir, plain_av)
    tool = require_hyperframes()

    present = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=60, cwd=project_dir,
    )
    assert present.returncode == 0, (
        f"positive control failed before the assumption could even be "
        f"exercised: {present.stderr}\n{present.stdout}"
    )
    for f in _renders(project_dir):
        f.unlink()

    (project_dir / "assets" / "input.mp4").unlink()
    missing = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=60, cwd=project_dir,
    )
    assert missing.returncode != 0, (
        "hyperframes render SUCCEEDED with assets/input.mp4 absent. "
        "flow.caption() depends on the composition actually reading that "
        "file as its video source -- if hyperframes now tolerates a "
        "missing source (e.g. falling back silently to a placeholder "
        "frame), the caption stage's black-frame guard is the only thing "
        "standing between a missing source and a silently wrong render, "
        "and that guard was never designed to catch this case."
    )


def test_video_src_resolves_from_project_root_not_from_hyperframes_json_paths_assets(
    tmp_path, plain_av
):
    """Assumption 4, reframed by direct measurement rather than assumed.

    Measured directly against the installed hyperframes CLI: `render` does
    NOT currently consult `hyperframes.json` to resolve a `<video src=...>`.
    A render succeeds identically whether `hyperframes.json` is absent,
    malformed, or declares a `paths.assets` that disagrees with reality, AS
    LONG AS the `src` attribute itself is a path relative to the PROJECT
    ROOT. A bare `src="input.mp4"` with `paths.assets: "media"` and the file
    actually living at `media/input.mp4` fails the same coverage gate as a
    genuinely missing file -- `paths.assets` is not consulted for resolution.

    So the shape cutline actually depends on here is narrower than "the
    config keys are honoured": it is flow.caption()'s hardcoded
    `project_dir / "assets"` staying in literal agreement with the
    composition's `src="assets/input.mp4"`, independent of
    `hyperframes.json` entirely. This test pins THAT, directly, and can go
    red in either direction: if `paths.assets` STARTS being honoured for src
    resolution (a welcome tightening, not a regression), the "should fail"
    half below unexpectedly succeeds; if project-root-relative resolution
    stops working at all, the "should succeed" half fails first.
    """
    tool = require_hyperframes()

    root_relative = tmp_path / "root_relative"
    _scaffold(root_relative, plain_av)  # src="assets/input.mp4", matches physical layout
    ok = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=60, cwd=root_relative,
    )
    assert ok.returncode == 0, (
        f"project-root-relative resolution failed to render at all: "
        f"{ok.stderr}\n{ok.stdout}"
    )

    mismatched = tmp_path / "mismatched"
    _scaffold(
        mismatched, plain_av,
        video_dir="media", hyperframes_paths_assets="media", video_src="input.mp4",
    )
    bad = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=60, cwd=mismatched,
    )
    assert bad.returncode != 0, (
        'hyperframes render SUCCEEDED using a bare src="input.mp4" resolved '
        'against hyperframes.json\'s paths.assets="media" rather than the '
        "project root. This means paths.assets STARTED being honoured for "
        "video src resolution -- a welcome tightening, not a regression, "
        "but flow.caption()'s hardcoded 'assets' directory name (and its "
        "assumption that hyperframes.json is otherwise decorative) should "
        "be reconsidered against this."
    )


def test_composition_width_height_and_duration_attributes_drive_the_render(
    tmp_path, plain_av
):
    """Assumption 5: the composition attribute vocabulary --
    `data-composition-id`, `data-start`, `data-duration`, `data-width`,
    `data-height`, `class="clip"` -- is actually READ, not merely tolerated.

    Measured directly: a composition scaffolded at 640x360 for 3 seconds
    (rather than the fixture's usual 1920x1080 / 6s) renders an artifact
    ffprobe reports as exactly 640x360, 3.0s. If hyperframes ever stops
    reading these attributes off the root `data-composition-id` element --
    falling back to a viewport default, say, or requiring a differently
    named attribute -- this fails on the ffprobe assertions below, naming
    the exact dimension that drifted, rather than surfacing as a silently
    mis-sized artifact that COMPOSITE_POLICY's geometry check (which treats
    a composite's geometry as legitimately becoming "the canvas size") would
    wave through as an expected change.
    """
    project_dir = tmp_path / "project"
    _scaffold(project_dir, plain_av, width=640, height=360, duration=3)
    tool = require_hyperframes()
    proc = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=60, cwd=project_dir,
    )
    assert proc.returncode == 0, f"render failed: {proc.stderr}\n{proc.stdout}"

    renders = _renders(project_dir)
    assert renders, f"render reported success but wrote nothing: {proc.stdout}"

    info = probe(renders[0])
    assert info.video is not None, "rendered artifact carries no video stream at all"
    assert (info.video.width, info.video.height) == (640, 360), (
        f"composition declared data-width=640 data-height=360 but the "
        f"render measured {info.video.width}x{info.video.height} -- the "
        "composition's sizing attributes are no longer driving output "
        "geometry"
    )
    assert info.duration == pytest.approx(3.0, abs=0.2), (
        f"composition declared data-duration=3 but the render measured "
        f"{info.duration:.2f}s -- the duration attribute is no longer "
        "honoured"
    )


# The added wall clock `data-no-timeline` removes, in seconds. Measured
# 2026-08-23 on this machine, hyperframes 0.8.10, the SAME composition rendered
# twice per row -- once with the attribute, once without:
#
#   condition              with     without    difference    ratio
#   idle                   5.2 s     94.4 s      89.2 s      18.2
#   idle                   4.3 s     94.4 s      90.1 s      22.0
#   all 18 cores busy     14.1 s    104.6 s      90.5 s       7.4
#   NEGATIVE CONTROL: attribute present but doing nothing
#   (both legs scaffolded WITHOUT it)
#                         94.8 s     94.8 s       0.0 s       1.00
#
# Read the columns. The DIFFERENCE moved 1.3 s across a 3.3x change in machine
# load; the RATIO moved 22.0 -> 7.4 and the with-attribute leg alone moved
# 4.3 -> 14.1. That is why this test no longer asserts an absolute bound on the
# fast leg, and why it does not assert a ratio either: what the attribute
# removes is a WALL-CLOCK poll timeout, which does not compress under CPU
# contention the way real work does, so the difference is the load-invariant
# quantity and both proxies for it are contaminated.
#
# The previous form asserted `fast_elapsed < 30` and said so itself -- "either
# this machine is under unusually heavy load, or data-no-timeline no longer
# skips the sub-composition poll" -- i.e. it could not distinguish the two, and
# two consecutive baseline runs on unmodified main gave 2 failed then 1 failed.
#
# 30 s sits between two MEASURED populations: 3.0x below the tightest working
# case (89.2 s) and 30 s above the broken one (0.0 s). It is also below the one
# ~45 s poll timeout the attribute skips, so any real skip must clear it.
MIN_SKIPPED_WALL_CLOCK_SECONDS = 30


def test_data_no_timeline_skips_the_subcomposition_readiness_poll(tmp_path, plain_av):
    """Assumption 6: `data-no-timeline` on the composition root actually
    skips HyperFrames' sub-composition timeline poll, rather than being a
    harmless, ignored attribute that hf_project's docstring only THINKS
    matters.

    Both renders run on the same machine in the same test, and the assertion
    is on the wall clock the attribute REMOVES -- see
    MIN_SKIPPED_WALL_CLOCK_SECONDS above for the measured populations and for
    why neither an absolute bound nor a ratio is the right instrument.

    Traced in the installed hyperframes CLI (`pollSubCompositionTimelines` in
    dist/cli.js): it polls every host carrying `data-composition-id` for a
    `window.__timelines[id]` registration that a GSAP-free static overlay never
    makes, and only proceeds, best-effort, once its ~45-second timeout lapses.
    """
    fast_dir = tmp_path / "fast"
    _scaffold(fast_dir, plain_av, no_timeline=True)
    tool = require_hyperframes()

    start = time.monotonic()
    fast = subprocess.run(
        [str(tool.path), "render", "."],
        capture_output=True, text=True, timeout=300, cwd=fast_dir,
    )
    fast_elapsed = time.monotonic() - start
    assert fast.returncode == 0, f"fast (data-no-timeline) render failed: {fast.stderr}"

    slow_dir = tmp_path / "slow"
    _scaffold(slow_dir, plain_av, no_timeline=False)
    start = time.monotonic()
    try:
        slow = subprocess.run(
            [str(tool.path), "render", "."],
            capture_output=True, text=True, timeout=300, cwd=slow_dir,
        )
        slow_elapsed = time.monotonic() - start
        slow_failed_outright = slow.returncode != 0
    except subprocess.TimeoutExpired:
        # A timeout IS the slow behaviour this half of the test expects --
        # not a test-infrastructure failure.
        slow_elapsed = time.monotonic() - start
        slow_failed_outright = False

    assert not slow_failed_outright, (
        "render WITHOUT data-no-timeline failed outright rather than "
        "merely being slow -- that is a different assumption breaking, not "
        "this one"
    )
    skipped = slow_elapsed - fast_elapsed
    assert skipped >= MIN_SKIPPED_WALL_CLOCK_SECONDS, (
        f"data-no-timeline saved only {skipped:.1f}s of wall clock "
        f"(with: {fast_elapsed:.1f}s, without: {slow_elapsed:.1f}s) -- expected "
        f"at least {MIN_SKIPPED_WALL_CLOCK_SECONDS}s, measured at 89-91s under "
        "loads from idle to fully saturated. Either the ~45s "
        "sub-composition-readiness timeout changed, or HyperFrames stopped "
        "polling for a timeline registration on GSAP-free compositions -- in "
        "which case data-no-timeline may no longer be doing anything, and the "
        "attribute's docstring on tests/conftest.py's hf_project fixture "
        "should be re-measured and possibly removed. Note this measures the "
        "DIFFERENCE, which is load-invariant, so 'the machine was busy' is not "
        "an explanation for a failure here."
    )
