# cutline

A verification spine for a two-source video pipeline.

> **Status — measured 2026-08-23.** v1 is implemented and merged; its acceptance criterion is
> **not** met. The orchestration, per-boundary verification, CLI and test suite exist and pass —
> 109 tests driving real ffmpeg, auto-editor and hyperframes binaries and asserting on ffprobe
> output rather than on mocks. **CI is green on `ubuntu-latest` and `macos-latest`**, which also
> settled a real question: ubuntu ships ffmpeg 6.1.1, and the floor in `tools.FFMPEG_FLOOR` exists
> because of it. **CI does not install auto-editor or hyperframes**, so both pipeline stages are
> exercised only on the operator's machine — see the spec's §6 for what that leaves uncovered.
>
> What has **not** happened: **no recording made for this project has been through the flow.**
> A real Apple-written `.mov` was put through the cut stage on 2026-08-23 to find out what a
> genuine capture does to it, and it found two blockers a synthetic fixture could not (an H.264
> profile the boundary could not satisfy, and a no-op gate comparing two different quantities);
> both are fixed. That is not the acceptance run — the Roadmap's v1 criterion names a recording
> made for this pipeline, cut *and* captioned. See [Roadmap](#roadmap).
>
> *This block asserts runtime facts, which have a truth-time. It carries a date for that reason —
> hyperframes alone moved 0.8.7 → 0.8.9 → 0.8.10 during v1's development, twice in one day. Tool
> versions are deliberately named in [Requirements](#requirements) as supported ranges rather than
> restated here as observations that go stale.*

`cutline` orchestrates existing tools and checks their work. It does not reimplement them.
[auto-editor](https://github.com/WyattBlue/auto-editor) cuts, HyperFrames captions and overlays,
OBS records; cutline owns the flow between them, the contract they exchange, and the verification
at every boundary.

## Why verification is the point

Every tool in a media chain reports its own success. None of them checks that the artifact
survived the *handoff*. Measured on ffmpeg 8.1.1:

> A 1920×1080 source carrying `rotation=90` side data, passed through a `trim`/`concat` filter
> graph, emerges as **1080×1920 with the side data gone**. Duration, frame count, stream count
> and codec are all unchanged — so every assertion a naive verifier would make still passes.

Phone-shot portrait footage is the ordinary case for talking-head video. A pipeline that chains
four tools and checks exit codes will ship silently wrong output. cutline is the thing that
catches that.

```
   [producers]              [the seam]            [consumers]

 silence analysis ──┐                         ┌──→ render  (ffmpeg)
 transcript   (v2) ─┼──→    EDL (JSON)   ─────┼──→ captions (v2)
 human editor (v3) ─┘       keep-segments     └──→ probe / report
```

## What is here

| module | what it does |
|---|---|
| `tools.py` | locates ffmpeg, ffprobe, auto-editor and hyperframes; pins their versions; refuses anything that is not the pinned auto-editor release by identifying it positively — a compiled image rather than a `#!` script |
| `probe.py` | ffprobe → `MediaInfo`: geometry, SAR/DAR, rotation side data, audio parameters, per-stream `start_time`, frame count |
| `verify.py` | compares two `MediaInfo`s under a per-boundary `Policy`; every checked property is classified `invariant` / `may_change` / `warn`, and an unclassified one is an error rather than a silence |
| `edl.py` | parses auto-editor `v3` and `v1` timelines into keep-segments **in integer frames** at a rational timebase |
| `flow.py` | `cut` → verify → `caption` → verify, stopping the flow at the first boundary that fails |
| `cli.py` | `cutline doctor · probe · cut · caption · run` |

`uv run cutline doctor` prints the four tools and their resolved versions and paths, or refuses
naming the first one missing and how to install it.

## The contract

Most media tools couple analysis to rendering: a function takes an MP4 and returns an MP4, and the
decisions it made are lost. That makes the interesting part — *what got cut and why* — invisible
and untestable.

auto-editor already solves this: it exports the timeline as a JSON document, and cutline
**consumes that rather than inventing a schema of its own**.

The accepted export names on 31.5.0 are **`v1`**, **`v3`**, `final-cut-pro` and `premiere` —
measured, by running them. `--export otio` and `--export json` are **both rejected**
(`Error! Unknown export format: otio`) even though the source tree carries an OTIO module; an
earlier revision of this file claimed auto-editor "emits OpenTimelineIO and JSON" and that was
read from the repository, not from the CLI. cutline consumes `v3`; `v1` parsing is a scoped
capability rather than a running cross-check.
Note that auto-editor **overrides the output extension**: `-o out.json --export v3` writes
`out.v3`, so the flow locates the artifact by the name auto-editor actually produced.

Internally cutline parses an EDL to a keep-segment list and enforces its invariants at the
boundary. What `edl._validate` actually checks: the list is **non-empty**, every segment has a
**positive duration**, no segment has a **negative** `start` or `offset`, and the segments —
**after being sorted by `start`** — do **not overlap**. It does *not* check the segments against
the source's duration; the parser is given the EDL alone and has no duration to check against.
Because the list arrives from a foreign tool, violations are **input validation** — they fail
loudly, naming the offending segment — not internal bugs.

## Requirements

- Python ≥ 3.12 (managed by [uv](https://docs.astral.sh/uv/); your system Python is untouched)
- `ffmpeg` and `ffprobe` on `PATH` — **6.0 or newer**, enforced as a floor by
  `tools.FFMPEG_FLOOR` (not a series pin: 9.x and later are accepted)
- [auto-editor](https://github.com/WyattBlue/auto-editor) **31.5.0**, exactly — **installed from
  GitHub releases, not pip.** auto-editor was rewritten in Nim; PyPI still serves a dead Python
  branch last published 2025-11-04. cutline detects a pip-installed auto-editor and refuses to run.
- HyperFrames **0.8.x** (`npm install -g hyperframes`), for the caption and overlay stages

### Upgrading hyperframes

`HYPERFRAMES_SERIES` is a speed bump, not a guarantee — the version number is a proxy for the
thing that actually breaks cutline, which is a change in the render CLI's *shape* (the `render`
subcommand, its cwd-relative output path, `assets/input.mp4`, the composition attribute
vocabulary, `data-no-timeline`). `tests/test_hyperframes_contract.py` is the real gate: one test
per assumption, each failing with a message naming which one moved.

When the pin refuses a newer hyperframes:

1. `npm install -g hyperframes@<new-version>`
2. `uv run pytest -m requires_hyperframes` — this runs the contract tests (and everything else
   marked `requires_hyperframes`) against it
3. All green → bump the `HYPERFRAMES_SERIES` string in `tools.py` and commit
4. Red → read which assumption's diagnostic fired. Some failures are good news (e.g. the cwd
   quirk being fixed upstream calls for simplifying `flow.caption()`, not reverting anything);
   others are real breaks that need a code change before the pin moves.

A scheduled workflow (`.github/workflows/upstream-check.yml`) runs these same tests weekly against
`hyperframes@latest` and opens an issue naming the version and what failed — it only reports; it
never bumps the pin itself.

## Verification

`cutline` does not report success from a subprocess exit code. Every artifact is verified by
probing it, and the test suite asserts on that probe rather than on mocks.

Duration, stream count, frame count and codec are **not sufficient** — that set is precisely what
the rotation defect above slips through. The checked set also carries width and height, SAR/DAR,
rotation side data, audio sample rate and channels, and each stream's `start_time` — because
cuts computed on the audio timeline drift when applied to the video timeline. Measured on
`tests/_fixtures/offset_streams.mp4`, a **synthetic** fixture built with ffmpeg `-itsoffset 0.5`:
video `0.000000`, audio `0.476009`. Earlier revisions of this file and of the spec attributed that
pair to "a real recorder" and claimed a synthetic fixture yields both at zero; re-measured, both
clauses were false and **no real-recorder measurement has been taken**.

A per-boundary policy names which properties must be identical and which may legitimately change,
and **the boundaries differ in kind** — measured, not assumed:

- **auto-editor (a cut)** preserves rotation, geometry and audio parameters. Duration and frame
  count may **shrink and only shrink**; a cut that produced a longer artifact is a violation.
  Direction alone does not bound magnitude, so the rendered frame count is additionally
  cross-checked against the keep-list auto-editor declared in its own EDL — measured across all
  eight fixture classes, those agree exactly, so a truncated render cannot pass as "a shrink".
  Where a container reports no frame count at all (a fragmented `.mov`, a Matroska remux) the
  count is **measured** by demuxing rather than exempted: 0.05 s on 88 s of 1080p, against 15 s
  for a full decode.
- **HyperFrames (a composite)** legitimately *consumes* rotation into a fixed canvas and takes the
  composition's duration, so both are permitted. A change in audio parameters is recorded as a
  **warning**, not a failure (measured: a 44.1 kHz mono source came out 48 kHz stereo,
  unannounced). The one property held invariant is the video codec.

Metadata cannot tell you whether a picture actually rendered, so the caption stage also measures
the frame content: it fails when **80% or more of the sampled pixels sit at or below the
limited-range black floor**. That is a pixel fraction rather than a whole-frame average on
purpose. Averaging the whole frame conflates "black render" with "correctly pillarboxed portrait
source" — measured, a correct 9:16-in-16:9 render averages 21.2 against a 20.0 mean-luma gate, a
6% margin, so most real portrait footage would have been rejected as black. As a pixel fraction
the same correct render reads 0.684 and a fully black one reads 1.000. Sampling is spread across
the whole timeline at 4 frames per second; an earlier version read the first twenty frames and
called it the video.

Two questions spec §4.1 raises for the composite boundary are **not implemented**: whether the
source was silently pillarboxed into a mismatched aspect, and whether the output audio parameters
are the *declared* ones rather than whatever the renderer chose. Both are deferred, and this file
previously claimed both as shipped behaviour.

This is why verification takes a policy rather than a fixed rule set.

### Tests

Fixtures are **generated by ffmpeg at test time and never committed**, so the repository stays
text-only. They are **not hermetic**: each generator writes once into `tests/_fixtures/` and every
later call — including in a later `pytest` invocation, not just the same session — returns the
file already on disk. Editing a generator therefore has **no effect** until the matching file is
deleted, and that trap has already produced a false green here: a mutation check on the `rotated`
generator passed against the stale cached file. `tests/conftest.py` documents it at the mutation
site. Delete the relevant file under `tests/_fixtures/` before trusting any fixture mutation.

```
uv run pytest                      # 86 tests, ~50s, needs all four binaries
uv run pytest -m "not requires_auto_editor and not requires_hyperframes"
```

CI is configured for `ubuntu-latest` and `macos-latest`. It installs ffmpeg (not preinstalled on
either runner image — measured against both manifests) and deselects the 21 tests that need
auto-editor or hyperframes, neither of which CI installs. `tools.FFMPEG_FLOOR` is `6` — a real
floor, not a series pin — measured against cutline's own source (nothing newer than roughly
ffmpeg 3) and its test fixtures (`-display_rotation`, tests-only, ffmpeg 6.0). **`ubuntu-latest`
ships ffmpeg 6.1.1**, which satisfies that floor, so the CI step calls
`cutline.tools.find_tool(floor=FFMPEG_FLOOR)` directly — the same check `cutline doctor` runs —
instead of reimplementing the comparison inline. An earlier version ran a bare `apt-get install
ffmpeg` under a step named "Assert ffmpeg major version" and then asserted the major was 8, which
could never hold on this runner.

**First run: 2026-08-23, green on both runners.** Before that push its steps had only been
checked by extracting them from the YAML and running them locally, which is why this section
previously said "green on a runner is not yet a fact about this repository" — it now is. The run
also produced the measurement the floor exists for: `ubuntu-latest` reported **ffmpeg 6.1.1**, so
the earlier `= 8` assertion would have failed there permanently, and a series pin would have
refused it as surely as a too-low one.

## Roadmap

Each version's acceptance criterion is what defines it as done. **v1 is not done**: the flow runs
end to end and every boundary is verified, including on a rotated portrait source, but the
criterion below names a *real recording* and none has been run through it.

| version | adds | done when |
|---|---|---|
| **v1** | verified recorded-source flow | a real recording goes cut → captioned, and **every boundary check the composite boundary actually gates on passes** — codec identity, a non-black render, stream counts, and at the cut boundary the full invariant set including rotation, geometry, profile and audio parameters; **the operator confirms the cut is USABLE**, not merely intact; the suite is proven able to go red against all **eight** fixture classes; **and a demonstrated RED** — a deliberately damaged artifact substituted at each boundary, which the boundary check rejects. |
| **v1.5** | own analyzer + renderer, as a *second* EDL producer behind the same interface — ⚠️ **contradicts §3.2's "out of scope in every version"; unresolved, see spec §8** | it renders the **first test subject** (spec §7.1), **preserves rotation**, and is benchmarked against auto-editor on the same file with the comparison published |
| v2 | faceless source path | a HyperFrames composition enters the same flow and passes the same boundary checks |
| v3 | MCP agent layer | an agent completes a full flow end to end, and **refuses** when a boundary check fails |
| v4 | recording, publishing | optional |

The design is specified in
[`docs/specs/2026-08-22-cutline-v1-design.md`](docs/specs/2026-08-22-cutline-v1-design.md).
It is at **revision 3**; §0 records what each revision changed and why, including the two
measurements earlier revisions got wrong.

## Licence

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
