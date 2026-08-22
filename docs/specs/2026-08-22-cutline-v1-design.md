# cutline v1 — Design

**Date:** 2026-08-22
**Revision:** 2 — supersedes rev 1 of the same date
**Status:** Ratified direction. Implementation plan pending.

---

## 0. Revision note

Rev 1 specified cutline as an implementation of silence detection: its own analyzer, its own
EDL, its own renderer. An adversarial review refuted the premise.

**What changed, and why:**

1. **auto-editor already ships this.** Rev 1 §8 claimed auto-editor's distinctive value was
   "motion detection and NLE round-trip export — out of v1 scope." That was false. Measured on
   the live repository at `31.5.0`: `--edit audio|motion|blackdetect|subtitle` (composable),
   `--margin 0.3s,1.5sec` (asymmetric — rev 1 listed this as an *open question*),
   `cmds/whisper`, and `exports/` emitting **otio · json · fcp7 · fcp11 · kdenlive · mlt ·
   shotcut**, plus three agent skills. Under the Unlicense. That is rev 1's v1, v2 and v3.
2. **Rev 1 read a corpse.** PyPI's `auto-editor 29.3.1` is a dead Python branch last uploaded
   2025-11-04. The project was **rewritten in Nim**; the repo root carries `ae.nimble` and
   `config.nims` and **no `pyproject.toml`**. Rev 1's "whichever installs is what gets recorded"
   would have benchmarked the corpse and labelled the result "auto-editor."
3. **Rev 1's scope boundary was wrong.** It confined cutline to talking-head footage and treated
   faceless content as HyperFrames' separate concern. The two share every stage after the source.

**cutline therefore orchestrates and verifies. It does not reimplement.**

---

## 1. Purpose

cutline is the spine of a two-source video operation: recorded talking-head footage for the
Sovereign SOUL and Sovereign Systems funnels, and faceless brand content for the content channel.

Today those are two unrelated workflows — different tools, different commands, no shared output
standard, and no single gate that says *this artifact is actually correct*. cutline is that
shared spine.

A secondary and explicit goal is that the repository serve as an applied-AI-engineering portfolio
artifact. The engineering on display is **integration architecture and verification across tool
boundaries**, not a reimplementation of a solved problem.

---

## 2. The problem cutline actually solves

**Every tool in this chain reports its own success. None of them checks that the artifact
survived the handoff.**

This is not hypothetical. Measured during adversarial review, on this machine's ffmpeg 8.1.1:

> A 1920×1080 source carrying `rotation=90` side data, passed through a `trim`/`concat` filter
> graph, emerges as **1080×1920 with the side data gone**. Positive control: `-c copy` preserves
> it. Duration, frame count, stream count and codec are all **unchanged** — so every assertion a
> naive verifier would make still passes.

Phone-shot portrait footage is the ordinary case for talking-head content. A pipeline that
chains four tools and checks exit codes will ship silently wrong video.

cutline's primary job is to be the thing that catches this.

---

## 3. Architecture

Two source pipelines, one contract, shared consumers:

```
  recorded   →  OBS (manual, v1)  →  auto-editor  →  EDL ──┐
                                                           ├─→  cutline
  faceless   →  HyperFrames composition  ────────────────────┘   verify
                                                                  ↓
                                                    captions / overlays  (HyperFrames)
                                                                  ↓
                                                            verify again
                                                                  ↓
                                                              deliverable
```

**Verification is not a final step. It runs at every boundary**, because the defect class in §2 is
introduced *by a handoff* and is invisible downstream of it.

### 3.1 The contract — consume, do not invent

auto-editor emits **OpenTimelineIO** and JSON. cutline consumes those rather than defining a
private schema.

Rev 1 defined a bespoke EDL. The adversarial review raised, as an unasked question, whether a
private schema beat a standard one. The pivot answers it: the producer already emits a standard,
so inventing one would mean writing an adapter *to our own format* for no gain.

cutline's internal model remains a keep-segment list with the rev-1 invariants — sorted,
non-overlapping, within `[0, duration]` — but it is a **parse target**, not a wire format.

**Invariant enforcement moves to the boundary.** Since the EDL now arrives from a foreign tool,
invariant violations are *input validation*, not internal bugs, and must fail with the offending
segment named.

### 3.2 Delegation — what cutline never implements

| capability | owner | cutline's role |
|---|---|---|
| recording | OBS (GPL-2.0, standalone use only) | none in v1; manual |
| silence / motion / black / subtitle cutting | **auto-editor** | invokes, pins, validates output |
| transcription | **auto-editor** (`cmds/whisper`) | invokes |
| captions, overlays, zooms, colour grade | **HyperFrames** | invokes |
| render | **auto-editor** | verifies the artifact |
| GUI timeline | OpenCut (MIT), if ever | none |
| **verification** | **cutline** | owns |
| **the flow between tools** | **cutline** | owns |
| **the agent surface** | **cutline** | owns |

Reimplementing anything in the upper rows is out of scope in every version. If a capability is
missing, the first question is whether to contribute it upstream.

---

## 4. Components

| module | responsibility | interface |
|---|---|---|
| `probe.py` | ffprobe → `MediaInfo`; the verification predicate | `Path → MediaInfo` |
| `verify.py` | compare two `MediaInfo`s across a boundary; report what changed | `MediaInfo, MediaInfo, Policy → Report` |
| `edl.py` | parse auto-editor OTIO/JSON → keep-segments; validate invariants | pure |
| `tools.py` | locate + version-pin auto-editor, ffmpeg, hyperframes; refuse on drift | `→ ToolVersions` |
| `flow.py` | the orchestration: source → cut → verify → caption → verify | composable steps |
| `cli.py` | `probe` · `verify` · `cut` · `caption` · `run` | typer |

`verify.py` is the centre of gravity. It is pure given two `MediaInfo` values, which makes the
most important logic the fastest to test.

### 4.1 What `verify()` checks

Rev 1 checked duration, stream count, frame count, codec. That set **passes the §2 rotation
defect**. The set is therefore:

| property | why |
|---|---|
| duration | the obvious one |
| frame count | catches truncation |
| codec, profile, pix_fmt | catches silent transcode changes |
| stream count + kinds | catches a dropped audio track |
| **width, height** | catches the §2 defect |
| **SAR / DAR** | catches non-square-pixel mangling |
| **rotation side data** | the §2 defect proper — present *and* value |
| audio sample rate, channels | catches resampling |
| **stream `start_time` per stream** | measured: a real recorder yields video `0.000000` and audio `0.476009`; a synthetic fixture yields both at zero. Cuts computed on the audio timeline and applied to the video timeline drift by that offset. |

A `Policy` names which properties must be *identical* across a boundary and which may legitimately
change (a cut changes duration and frame count; nothing may change rotation).

---

## 5. Error handling

| condition | behaviour |
|---|---|
| a required tool is absent | fail at startup, naming the tool and how to install it |
| **auto-editor installed from pip** | **fail loudly** — detect and refuse; PyPI ships a dead Python branch (§0.2) |
| tool version outside the pinned range | refuse, naming both versions; never silently proceed |
| EDL fails an invariant | fail with the offending segment printed, as input validation |
| EDL is empty, or keeps ≈ 100% of source | short-circuit — no re-encode, no generation loss, exit explaining why |
| a boundary check fails | **stop the flow**; never hand a corrupted artifact to the next stage |
| any tool exits non-zero | surface its stderr verbatim |
| **any tool exits zero but its artifact fails verification** | **fail** — this is the case §2 exists for |
| long operation interrupted | leave the last verified artifact in place; report which stage completed |

---

## 6. Testing

**Fixtures are generated by ffmpeg at test time**, never committed.

Rev 1's fixture set was two cases: silence-at-known-timestamps, and continuous audio. Adversarial
review showed that distribution cannot produce the defects that actually occur. The required set:

| fixture | defect it exposes |
|---|---|
| silence at known timestamps | the happy path |
| continuous audio, no silence | positive control — the detector must be able to return *nothing* |
| **silence at t=0** | emits `silence_start: 0` — a **bare integer**, which a `\d+\.\d+` parser misses |
| **silence running to EOF** | measured: `silence_end: 10.0078` against a `10.000000` duration — inverts to a segment with `start > end` |
| **divergent stream start_time** | built with `-itsoffset`; video `0.000000`, audio `0.476009` |
| **video carrying `rotation=90`** | the §2 defect |

**Positive control is required** and applies to the *fixture generator* as well as the detector: a
generator that cannot produce a dirty input has not shown the suite capable of red.

**Mutation check:** break the parser and the boundary comparator deliberately; the suite must go
red **against the fixtures above**, not merely against the happy path.

### CI

GitHub Actions on `ubuntu-latest` and `macos-latest`.

**ffmpeg is NOT preinstalled on either runner.** Rev 1 asserted it was; measured against both
runner-image manifests with positive controls, the string does not appear. CI must install it and
**pin the version**, or a runner-image bump reddens the suite with no code change — and green CI
would otherwise say nothing about the operator's ffmpeg 8.1.1 homebrew arm64 build.

---

## 7. v1 scope

**In:** tool discovery and version pinning · OTIO/JSON EDL parsing and validation · the full
`verify()` property set · a single orchestrated flow, *recorded* source: auto-editor cut →
verify → HyperFrames captions → verify · CLI · tests · CI.

**Out:** recording, the faceless source path, MCP, GUI, publishing, thumbnails, any
reimplementation of a §3.2 upper-row capability.

The faceless path is deferred not because it is hard but because verifying one path properly
teaches what the second one needs.

---

## 8. Roadmap and acceptance criteria

Each version is done when its criterion is met. Nothing is done by default.

| version | adds | done when |
|---|---|---|
| **v1** | verified recorded-source flow | a real recording goes cut → captioned with **every boundary verified**, including rotation on a portrait source; the suite is proven able to go red against all six fixture classes |
| v2 | faceless source path | a HyperFrames composition enters the same flow and passes the same boundary checks |
| v3 | MCP agent layer | an agent completes a full flow end to end, and **refuses** when a boundary check fails |
| v4 | recording, publishing | optional |

---

## 9. Toolchain

`uv`, Python pinned `>=3.12`. System Python is 3.9.6 and is left untouched.

**auto-editor is installed from GitHub releases** (`auto-editor-macos-arm64`, tag `31.5.0`),
**never from pip** — see §0.2 and §5.

Tool versions are pinned and asserted at runtime. Every tool here is pre-1.0 or fast-moving;
auto-editor changed implementation language inside a year. The CLI surface survived that rewrite,
which is the evidence that the CLI — not any internal API — is the durable contract.

---

## 10. Repository layout

**Target state. The directories are currently empty.**

```
cutline/
  pyproject.toml  .python-version   uv, Python >=3.12
  README.md  LICENSE  NOTICE        Apache-2.0
  src/cutline/   probe · verify · edl · tools · flow · cli
  tests/         conftest.py (six fixture generators) + per-module
  .github/workflows/ci.yml          ffmpeg installed + version-pinned
  docs/specs/                       this document
```

---

## 11. Decisions and reasoning

| decision | choice | why | cost accepted |
|---|---|---|---|
| build vs adopt | orchestrate, don't reimplement | the capabilities exist; the integration does not | dependent on upstream CLIs |
| update flow | pin CLIs, not internals | the Nim rewrite preserved the CLI — proven durable | must track CLI changes |
| EDL format | consume auto-editor's OTIO/JSON | the producer already emits a standard | bound to its schema |
| verification | own it, at every boundary | the one thing no tool in the chain does | runtime cost per stage |
| render | delegate to auto-editor | reimplementing gains nothing | see below |
| runtime | Python | matches existing body of work; the Applied-AI-Engineer lane | — |
| licence | Apache-2.0 | express patent grant; matches HyperFrames upstream | — |
| scope | recorded path first | verifying one path properly teaches the second | faceless waits |

**Render, recorded for the path not taken.** Rev 1 specified a single `filter_complex` trim+concat
and rejected segment-then-concat on ergonomics without measuring it. Measured at 1080p/300s:
trim/concat N=100 → 14.6 s, N=400 → **168.2 s**, scaling ≈ **O(N^1.6)**; segment-extract + concat
demuxer at N=400 → **33.0 s**, i.e. **5.1× faster** but with 3.9 % duration drift from input-side
keyframe snapping, untuned. `select`/`aselect` **fails outright** at N=400 (*Cannot allocate
memory*). Since v1 delegates rendering, this is a recorded finding rather than a live decision. If
cutline ever renders, the ratified approach is **adaptive**: choose by cut count, with the
crossover measured rather than guessed.

---

## 12. Findings carried from adversarial review

Rev 1 was reviewed adversarially; verdict REVISE, 15 findings.

**Resolved by this revision:** the false auto-editor capability claim · the pip/GitHub version trap
· the bespoke-schema question · the public present-tense capability overclaim · missing per-version
acceptance criteria · the unmeasured render tradeoff.

**Carried into this design as requirements:** rotation and geometry in `verify()` (§4.1) · the four
missing fixture classes (§6) · divergent stream `start_time` (§4.1, §6) · CI must install and pin
ffmpeg (§6) · no-op short-circuit to avoid generation loss (§5) · interrupt policy (§5) · layout
labelled target-state (§10).

**Not applicable after the pivot:** the `-vn` optimisation and the margin-clamp arithmetic — both
belonged to an analyzer cutline no longer implements. If auto-editor's margin handling produces
out-of-range segments, §3.1 catches it as input validation.

---

## 13. Open questions

1. **auto-editor's real cut-count per hour of speech.** Unmeasured — no recording exists. It sizes
   nothing in v1 (render is delegated) but will size the flow's wall-clock.
2. **Does auto-editor's OTIO export preserve rotation?** Unknown. If it does not, §2's defect is
   present inside a dependency and the boundary check is the only thing that will catch it.
3. **HyperFrames' caption stage as a boundary.** Unmeasured whether it alters geometry or timing.
   §4.1's policy for that boundary is provisional until it is.
4. **Version-pin range policy** — exact pin or floor? Exact is safer and noisier; unresolved.
