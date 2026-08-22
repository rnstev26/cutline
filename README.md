# cutline

A verification spine for a two-source video pipeline.

> **Status: pre-implementation.** The repository currently contains a design specification and
> nothing else — no source, no tests, no CI. Everything below the Roadmap heading describes
> intended behaviour, not shipped behaviour.

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

## Roadmap

Nothing here has shipped. Each version's acceptance criterion is what defines it as done.

| version | adds | done when |
|---|---|---|
| **v1** | verified recorded-source flow | a real recording goes cut → captioned with **every boundary verified**, including rotation on a portrait source; the suite is proven able to go red against all six fixture classes |
| **v1.5** | own analyzer + renderer, as a *second* EDL producer behind the same interface | it renders the test subject, **preserves rotation**, and is benchmarked against auto-editor on the same file with the comparison published |
| v2 | faceless source path | a HyperFrames composition enters the same flow and passes the same boundary checks |
| v3 | MCP agent layer | an agent completes a full flow end to end, and **refuses** when a boundary check fails |
| v4 | recording, publishing | optional |

The design is specified in
[`docs/specs/2026-08-22-cutline-v1-design.md`](docs/specs/2026-08-22-cutline-v1-design.md).
It is at **revision 2**, rewritten after an adversarial review refuted rev 1's premise; §0 of
the spec records what changed and why. Treat it as the record of intent, not of shipped behaviour.

## The contract

Most media tools couple analysis to rendering: a function takes an MP4 and returns an MP4, and the
decisions it made are lost. That makes the interesting part — *what got cut and why* — invisible
and untestable.

auto-editor already solves this, and emits **OpenTimelineIO** and JSON. cutline **consumes those
rather than inventing a schema of its own** — the producer already speaks a standard, so defining
a private format would mean writing an adapter to ourselves for no gain.

Internally cutline parses an EDL to a keep-segment list with enforced invariants (sorted,
non-overlapping, within `[0, duration]`). Because that list arrives from a foreign tool, invariant
violations are **input validation** — they fail loudly, naming the offending segment — not
internal bugs.

## Requirements

- Python ≥ 3.12 (managed by [uv](https://docs.astral.sh/uv/); your system Python is untouched)
- `ffmpeg` and `ffprobe` on `PATH`
- [auto-editor](https://github.com/WyattBlue/auto-editor) — **installed from GitHub releases, not pip.**
  auto-editor was rewritten in Nim; PyPI still serves a dead Python branch last published
  2025-11-04. cutline detects a pip-installed auto-editor and refuses to run.
- HyperFrames, for the caption and overlay stages

## Verification

`cutline` does not report success from a subprocess exit code. Every artifact is verified by
probing it, and the test suite asserts on that probe rather than on mocks.

Duration, stream count, frame count and codec are **not sufficient** — that set is precisely what
the rotation defect above slips through. The checked set also carries width and height, SAR/DAR,
rotation side data, audio sample rate and channels, and each stream's `start_time` (measured: a
real recorder yields video `0.000000` and audio `0.476009`; a synthetic fixture yields both at
zero, so cuts computed on the audio timeline drift when applied to the video timeline).

A per-boundary policy names which properties must be identical and which may legitimately change,
and **the boundaries differ in kind** — measured, not assumed:

- **auto-editor (a cut)** preserves rotation, geometry and audio parameters; duration and frame
  count shrink. Anything else changing is a defect.
- **HyperFrames (a composite)** legitimately *consumes* rotation into a fixed canvas and takes the
  composition's duration. There the useful questions are different: was the source silently
  pillarboxed into a mismatched aspect, are the audio parameters the declared ones (measured: a
  44.1 kHz mono source came out 48 kHz stereo, unannounced), and is the frame actually non-black?

This is why verification takes a policy rather than a fixed rule set.

Test fixtures are **generated by ffmpeg at test time**, never committed, so the repository
stays text-only and the tests stay hermetic.

## Licence

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
