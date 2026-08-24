# cutline v1 — Design

**Date:** 2026-08-22
**Revision:** 4 — supersedes rev 3 of the same date
**Status:** Ratified direction. v1 is **implemented**; its §8 acceptance criterion is **not yet
met** — no recording made for this project has been run through the flow. See §0.1 for what rev 3
corrected and §0.2 for what rev 4 measured.

---

## 0. Revision note

Rev 1 specified cutline as an implementation of silence detection: its own analyzer, its own
EDL, its own renderer. An adversarial review refuted the premise.

**What changed, and why:**

1. **auto-editor already ships this.** Rev 1 §8 claimed auto-editor's distinctive value was
   "motion detection and NLE round-trip export — out of v1 scope." That was false. Measured on
   the live repository at `31.5.0`: `--edit audio|motion|blackdetect|subtitle` (composable),
   `--margin 0.3s,1.5sec` (asymmetric — rev 1 listed this as an *open question*),
   `cmds/whisper`, and `exports/` carrying **otio · json · fcp7 · fcp11 · kdenlive · mlt ·
   shotcut** source modules, plus three agent skills. *(Of those, the CLI accepts `v1`, `v3`,
   `final-cut-pro` and `premiere`; see §3.1.)* Under the Unlicense. That is rev 1's v1, v2 and v3.
2. **Rev 1 read a corpse.** PyPI's `auto-editor 29.3.1` is a dead Python branch last uploaded
   2025-11-04. The project was **rewritten in Nim**; the repo root carries `ae.nimble` and
   `config.nims` and **no `pyproject.toml`**. Rev 1's "whichever installs is what gets recorded"
   would have benchmarked the corpse and labelled the result "auto-editor."
3. **Rev 1's scope boundary was wrong.** It confined cutline to talking-head footage and treated
   faceless content as HyperFrames' separate concern. The two share every stage after the source.

**cutline therefore orchestrates and verifies. It does not reimplement.**

### 0.1 Rev 3 — one measurement was false

Rev 2's §4.1 stated: *"measured: a real recorder yields video `0.000000` and audio `0.476009`;
a synthetic fixture yields both at zero."*

Re-measured against `tests/_fixtures/offset_streams.mp4`, which is a **synthetic** fixture built
with ffmpeg `-itsoffset 0.5`: video `0.000000`, audio `0.476009` — byte-identical to the pair
attributed to a real recorder. So the second clause was false outright, and the identical value
says the first clause's "real recorder" was this same synthetic file all along. **No real-recorder
measurement has ever been taken for this spec.**

The property is still worth checking and the fixture still exercises it; what was wrong was the
provenance, and provenance is what makes a measurement worth anything. §4.1 now says where the
number came from. This is the third spec-honesty correction; the standing rule it enforces is that
a figure must name the artifact it was read off.

### 0.2 Rev 4 — the adversarial review's predictions, measured

`docs/reviews/2026-08-22-cutline-v1-adversary.md` raised 22 findings against rev 3 and was explicit
that it **executed nothing**: every finding is labelled `[TEXT]` (the contradiction is on the page)
or `[PREDICTED]` (inferred from documented tool behaviour, and listed again as "something to
measure before trusting"). Rev 4 is the measuring pass. §7 of that file now carries a verdict table:
per finding, the command run and what it returned.

**Three things were refuted by measurement** and are recorded so nobody re-derives them: a
speed-adjusted `v3` timeline does **not** break the frame-count gate (`dur` counts output frames, so
the render matched the EDL exactly at 68); auto-editor's `v1` export **does** carry the `timebase`
key the parser requires; and an all-silence source does **not** traceback — auto-editor refuses it
first with "Timeline is empty, nothing to do" and the CLI surfaces that verbatim.

**Two blockers the review did not find were found by running a real recording through the flow.**
Both would have failed the §8 acceptance run for reasons unrelated to what it is meant to prove:

1. **`video.profile` is an invariant this boundary could not satisfy.** A real Apple-written `.mov`
   (H.264 **Main**) rendered as H.264 **High** — auto-editor's libx264 default — and the cut was
   refused on a healthy render. `flow._profile_args` now declares the source's profile to the
   renderer (`-profile:v`), which auto-editor exposes; the invariant is unchanged. See §4.1.
2. **The no-op short-circuit compared two different quantities** and could copy a source through
   unedited while reporting `[cut] OK` — the §2 failure shape, in cutline itself. See §5.

**And one measurement retires a standing unknown.** §4.1 said of divergent stream `start_time`:
"whether real capture hardware diverges by a similar amount is UNMEASURED." Measured 2026-08-23 on
two real Apple-written captures on this machine (an 88.6 s 1080p and a 79.0 s clip): video
`0.000000`, audio `0.000000` on **both**. Real capture, at least this recorder, does **not** diverge.
The synthetic fixture remains the only source of the `0.476009` figure and the property is still
worth checking; what is now measured is that the hazard's premise is not general.

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

**Where the defect actually lives — measured 2026-08-22.** auto-editor 31.5.0 **preserves**
rotation and geometry through its own render:

| | width×height | rotation | frames | duration |
|---|---|---|---|---|
| source | 1920×1080 | **90** | 360 | 12.000 |
| after auto-editor | 1920×1080 | **90** | 281 | 9.381 |

(0.92 s; fixture built with `-display_rotation 90`, positive-controlled to confirm it carried the
side data before the run.)

**The `90` in these tables is the fixture's value, not a universal one — measured 2026-08-23.**
ffprobe reports the rotation as read out of the display matrix, and on real portrait capture from an
Apple device that value is **`-90`**, not `90`. cutline is unaffected: it compares before against
after and never interprets the number. Anything that *reasons* about the value — a future reframe
stage, a caption placement rule — must not read these tables as saying portrait is `90`.

So the defect is **not universal** — it belongs to naive filter-graph rendering, which is exactly
what rev 1 specified and rev 2 delegates away. This does not retire the verification case; it
**relocates** it. The suspect boundaries are now the **HyperFrames caption stage** and any custom
ffmpeg step, both unmeasured. And since we hold positive proof that a `trim`/`concat` graph
destroys rotation silently, any stage built on one is suspect until measured.

**The HyperFrames boundary — measured 2026-08-22, and it behaves differently in kind.** A
rotated source (1920×1080, `rotation=90`, i.e. displaying as 1080×1920 portrait) put through a
HyperFrames composition and rendered:

| property | source | after HF |
|---|---|---|
| rotation side data | 90 | **absent** |
| width × height | 1920×1080 | 1920×1080 *(the canvas, not the source)* |
| **visual orientation** | portrait | **portrait — correct, verified by frame extraction** |
| audio | 44100 Hz, **mono** | 48000 Hz, **stereo** |
| duration | 12.0 | 6.0 *(the composition's, not the source's)* |

**HyperFrames is a re-composite, not a passthrough.** Chrome honours the display matrix when
playing the video, so the footage is rendered **upright** — there is no sideways-video defect. But
the output is a fresh render at the composition's canvas size, so rotation side data is
legitimately gone and geometry is legitimately the canvas's.

Two consequences, both real:

1. **A portrait source in a landscape composition is silently pillarboxed.** Visible in the
   measurement above as black bars. Not corruption — but not usually what was intended either,
   and nothing in the chain says so.
2. **Audio is silently resampled and up-mixed.** 44.1 kHz mono became 48 kHz stereo with no
   warning. Rev 1's property set would not have noticed.

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

auto-editor emits its own JSON timeline formats. cutline consumes those rather than defining a
private schema.

Rev 1 defined a bespoke EDL. The adversarial review raised, as an unasked question, whether a
private schema beat a standard one. The pivot answers it: the producer already emits a documented
format, so inventing one would mean writing an adapter *to our own format* for no gain.

**Measured 2026-08-22 — correcting an earlier claim in this spec.** `--export otio` is
**rejected** by the 31.5.0 binary despite `src/exports/otio.nim` existing in the source. The
accepted names are **`v1`**, **`v3`**, `final-cut-pro`, `premiere`. cutline therefore consumes
`v3`; `v1` **parsing** is a scoped capability. *(An earlier revision said "OTIO"; that was read from
the source tree, not from the CLI. Rev 3 said "`v1` as a cross-check" here and in §11 — measured,
no stage runs one, nothing compares the two exports, and no section said what a disagreement would
mean. A cross-check that exists nowhere in the architecture is a claim, not a control, so the phrase
is withdrawn rather than left to read as a shipped gate.)*

Note also: **auto-editor overrides the output extension.** `-o out.json --export v3` writes
`out.v3`. The flow must locate the artifact by the name auto-editor actually produced, not the one
it asked for.

**`v3` is the richer target and is the primary:**

```json
{ "version": "3", "timebase": "30/1", "resolution": [1920, 1080],
  "samplerate": 44100, "layout": "mono",
  "v": [[{ "src": "in.mp4", "start": 0, "dur": 97, "offset": 0, "stream": 0 }, …]],
  "a": [[…]] }
```

`v1` is simpler — `chunks: [[start, end, speed], …]`, where a speed of `99999.0` marks a removed
span and `1.0` a kept one. **Measured 2026-08-23:** the `v1` export carries `timebase` (`"30/1"`),
which the parser requires and which had not been confirmed.

**Field semantics, measured rather than inferred.** `--set-speed 2.0,0,1.5sec --export v3` against a
90-frame source produced `{start: 0, dur: 23, offset: 0, effects: ["speed:2.0"]}` followed by
`{start: 23, dur: 45, offset: 45}`. So **`start` indexes the output timeline, `offset` indexes the
source, and `dur` is a length in OUTPUT frames** — 23 output frames for the 45 source frames the
2.0 speed consumed. At unit speed the two lengths coincide, which is why v1 may treat `dur` as both.

**The scope gate is format-independent, not `v1`-only.** A speed adjustment is not a `speed` field:
it appears as an `effects` list on the clip, and an ordinary `--edit audio` export carries no
`effects` key at all. Any `v3` clip carrying **any** effect is now **refused by name** — fail-closed,
because an effect nobody has measured is not evidence that ignoring it is safe. *(Recorded because it
refutes the obvious worry: the speed timeline's render carried 68 frames, exactly its EDL's
keep-total, so the frame-count gate does **not** misfire on one. The gap was narrower than it looked
and real all the same, since `parse` is a public entry point.)*

**Units are integer FRAMES at a rational timebase, not float seconds.** `timebase` is a rational
string (`"30/1"`) and must be parsed as one, never assumed to be 30 or coerced to float. Frame
arithmetic is exact; seconds arithmetic accumulates rounding drift across hundreds of cuts.
cutline's internal model is therefore a keep-segment list **in frames**, converting to seconds
only for display.

`v3` also carries `resolution`, `samplerate` and `layout` — precisely the properties `verify()`
needs, so the EDL doubles as a **declared expectation** to check the rendered artifact against.

**Invariant enforcement moves to the boundary.** Since the EDL arrives from a foreign tool,
invariant violations are *input validation*, not internal bugs, and must fail with the offending
segment named. `v1` speeds other than `1.0` / `99999.0` are legal (auto-editor supports speed
changes) and must be rejected explicitly in v1 scope rather than silently treated as keeps.

**Validation is parse-pure PLUS one source-dependent check.** Ordering, positivity, non-overlap and
the speed/effect vocabulary are all properties of the keep-list considered **alone**, and a pure
parser can enforce them. "Out of range" is not: it means out of range **of the source**, and rev 3
asserted (§12) that §3.1 caught it when nothing did. Measured — a `v3` timeline declaring a single
999999-frame keep against a 90-frame source parsed clean, validated clean and reached the render,
where the only quantitative gate compares the render against *that same EDL*, so an over-claiming
EDL and a padded render agree with each other.

Every segment must therefore end at or before the source's last **timeline** frame, and that one
invariant needs the source's measured length, so it lives in the orchestrator (`flow.cut`) rather
than in the pure parser. **Timeline frames, not video-stream frames**, because those differ and the
EDL counts the former — see §5's no-op entry for what conflating them cost.

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
| `edl.py` | parse auto-editor `v3`/`v1` JSON → keep-segments **in frames**; validate invariants | pure |
| `tools.py` | locate + version-pin auto-editor, ffmpeg, hyperframes; refuse on drift | `→ ToolVersions` |
| `flow.py` | the orchestration: source → cut → verify → caption → verify | composable steps |
| `cli.py` | `doctor` · `probe` · `cut` · `caption` · `run` | typer |

(`verify` was listed here and has never been a command; `doctor` ships and was unlisted, while §6
and §13.4 both refer to `cutline doctor` as though this row had introduced it.)

`verify.py` is the centre of gravity. It is pure given two `MediaInfo` values, which makes the
most important logic the fastest to test.

**The "declared expectation" is only half-wired, and this says which half.** §3.1 promises that
`v3`'s `resolution` / `samplerate` / `layout` let the EDL double as an expectation to check the
render against. `verify()`'s signature is `MediaInfo, MediaInfo, Policy → Report` — there is no
parameter for a declared expectation to arrive through, and measured, `edl.py` parses those three
fields into `Edl` and **no module reads them back**. The one expectation check that exists (frame
count) is in the orchestrator, not the verifier.

What v1 *does* now declare runs in the other direction: `flow._profile_args` reads the source's
measured video profile and tells the renderer to preserve it (§4.1). Checking a render against its
own EDL's declared resolution / sample rate / layout remains **unbuilt**, and §4.1's composite
question "are the output audio parameters the *declared* ones" therefore still has no place to be
answered. Stated as an open item rather than implied as shipped.

### 4.1 What `verify()` checks

Rev 1 checked duration, stream count, frame count, codec. That set **passes the §2 rotation
defect**. The set is therefore:

| property | why |
|---|---|
| duration | the obvious one |
| frame count | catches truncation |
| codec, profile, pix_fmt | catches silent transcode changes |
| stream count + kinds | catches a dropped audio track. **Expressible since rev 4** — the model addresses `video.*` / `audio.*` in the SINGULAR and resolves each first-of-kind, so a source that lost one of two identical audio tracks matched on every named property and reported OK. `MediaInfo.video_streams` / `.audio_streams` are now checked properties. **Counts, not an ordered kinds tuple, and that is measured:** auto-editor 31.5.0 preserves audio streams (1→1 and 2→2) and **drops `data` streams** — a real Apple `.mov` carrying (audio, video, data, data) rendered as (video, audio) — so counts can be invariant at the cut boundary and an ordered all-kinds tuple could not be. Non-a/v streams are outside v1's model by that measurement, not by oversight. |
| **width, height** | catches the §2 defect |
| **SAR / DAR** | catches non-square-pixel mangling |
| **rotation side data** | the §2 defect proper — present *and* value |
| audio sample rate, channels | catches resampling |
| **video profile** | **added as a per-boundary concern in rev 4.** §4.1 already called profile a "silent transcode change" catcher and the cut boundary could not satisfy it: measured, a real Apple `.mov` at H.264 **Main** rendered H.264 **High** (auto-editor's libx264 default) and the boundary refused a healthy render. `flow._profile_args` now passes the source's measured profile to `-profile:v`, which auto-editor exposes; measured, the same file then rendered Main with an unchanged frame count. The invariant is **not** relaxed — an unmapped profile passes no argument and `verify()` still compares it, so a renderer that changes it still fails. Only H.264 is mapped: measured, an HEVC source came back HEVC/Main unasked. |
| **stream `start_time` per stream** | measured on `tests/_fixtures/offset_streams.mp4` — a **synthetic** fixture, ffmpeg `-itsoffset 0.5` (the request lands at 0.476009 after container timescale rounding): video `0.000000`, audio `0.476009`. Cuts computed on the audio timeline and applied to the video timeline drift by that offset. **Correction (rev 3):** earlier revisions attributed this pair to "a real recorder" and added "a synthetic fixture yields both at zero". Both clauses were false — re-measured, the synthetic fixture is exactly where the number came from, and **no real-recorder measurement has been taken**. **ANSWERED 2026-08-23:** two real Apple-written captures on this machine (88.6 s 1080p; 79.0 s) report video `0.000000` and audio `0.000000` — **no divergence**. The synthetic fixture is still the only source of `0.476009`. **Per-boundary classification (the row this property was missing):** `may_change` at BOTH boundaries, and deliberately so — the hazard rev 3 describes is that the offset existed *when the cut was computed*, which is a property of the INPUT, not a delta across a handoff. Comparing before-offset to after-offset cannot detect it. An input pre-condition check is **not built**: the threshold would have to be chosen, and the only population measured so far is one synthetic file and two real captures at zero. |

A `Policy` names which properties must be *identical* across a boundary and which may legitimately
change. **The policy is per-boundary, and "nothing may change rotation" is wrong as a global
rule** — measured, the two boundaries differ in kind:

| boundary | rotation | geometry | duration | audio params | stream counts | `start_time` |
|---|---|---|---|---|---|---|
| **auto-editor** (cut) | **must be identical** — measured, it is | must be identical | may shrink | must be identical | **must be identical** (measured: preserved) | may change — see the row above |
| **HyperFrames** (composite) | legitimately **consumed** into the canvas | legitimately becomes the **canvas** size | becomes the **composition's** | must be **declared**, not discovered | **warn** — v1's composition takes one of each and emits one of each, so this never fires on the v1 path; it is for v2's compositions | may change |

**On "may shrink" for duration, and why it is still an exact comparison.** The review's F20 predicted
that encoder priming/padding could push a correct render's `format.duration` past the source's, and
it does: measured, a fragmented `.mov` source at 3.066667 s rendered at 3.088254 s — a **+0.0216 s
growth** — and the boundary refused it. A tolerance was the obvious fix and is the wrong one, because
the growth had a cause. It only appears when the render materialises a timeline the cut removed
essentially nothing from, and that is the **no-op path**, which was not being taken (see §5). With
the no-op gate comparing the right quantity, that input short-circuits to a byte-for-byte copy and
the duration is unchanged; re-measured across six containers after the fix, every duration **shrank**.
So the cause was removed rather than tolerated, and no threshold was invented.
**Residual, and it is a contract question rather than a defect:** `verify(..., CUT_POLICY)` is public
and still compares `format.duration` for exact float equality with a one-directional constraint. On
an artifact pair not produced by `flow.cut()` that exactness can still bite. Deliberately left as-is
— the honest bound is one video frame period plus one audio frame period, and the audio term is not
readable from any ffprobe header field measured here, so setting it would mean guessing the quantity
it gates.

For the HyperFrames boundary the meaningful checks are therefore different questions:

- did the source's **display aspect** match the composition canvas, or was it silently
  pillarboxed? (warn, do not fail — it may be intended)
- are the output audio parameters the **declared** ones, rather than whatever the renderer chose?
- is the visual content actually present, rather than a correctly-sized black frame? **The gate
  AVERAGES, so it can only see *mostly* black — measured 2026-08-23.** A render whose first 25% is
  entirely black and whose remaining 75% is correct measures a black-pixel ratio of **0.2500**
  against the 0.80 gate: passed, reported OK. Partial content loss is both likelier than total loss
  and invisible to a mean. The honest statement of the check is "no sustained black RUN exceeding a
  stated duration", and §13.6's threshold governs the per-frame ratio rather than the aggregate.
  **Not changed here:** picking a run-length would mean picking a duration nothing has measured, and
  the aggregation change is a gate redesign, not a threshold tweak. Recorded as a known blind spot
  with its number.

This is why `verify()` takes a `Policy` rather than a fixed rule set. Rev 2 had the concept right
and the default wrong.

---

## 5. Error handling

| condition | behaviour |
|---|---|
| a required tool is absent | fail at startup, naming the tool and how to install it |
| **auto-editor installed from pip** | **fail loudly** — refuse anything that is not the pinned release, by POSITIVE identification. The criterion, not just the outcome: the resolved binary must be a **compiled image**, not a script. Measured 2026-08-23 — pipx and uv both emit console scripts that are text beginning with `#!` (`#!/bin/sh`, `#!/…/bin/python`), while the release is Mach-O (`cf fa ed fe`). The previous rule was "a file named `python` sits in the same directory", which **refused the documented happy path**: §9 installs the correct binary into `~/.local/bin`, where pipx and uv also drop a `python` — measured, a symlink to the genuine 31.5.0 binary beside such a file was rejected as pip-installed. §9's sha256 is deliberately NOT the gate: it is one platform's asset and would refuse a legitimate Linux or x86_64 build. |
| tool version outside the pinned range | refuse, naming both versions; never silently proceed |
| EDL fails an invariant | fail with the offending segment printed, as input validation |
| **EDL is empty** (everything was cut) | **auto-editor refuses first** — measured on an all-silence source, it exits 1 with `Error! Timeline is empty, nothing to do.`, which surfaces verbatim as a `FlowError` and a clean exit 1. If a future version emits an empty timeline instead, `edl._validate` raises `EdlError` — which the CLI now catches (it subclasses `ValueError` and used to escape as a traceback). Two opposite conditions, previously collapsed into one row with one behaviour. |
| **EDL keeps ≈ 100% of the source TIMELINE** | short-circuit — copy, no re-encode, no generation loss. **The comparison is timeline frames against timeline frames**, and getting that wrong was a live silent-wrong-artifact bug: the EDL's keep-total counts timeline frames at its own timebase, while `video.nb_frames` counts frames in the video stream, and those differ whenever the container's declared duration exceeds the video stream's length. Measured on a source carrying 6 s of video and 12 s of audio with real silence, the EDL kept **281 of 360** timeline frames — a real cut — and `281 >= 180 * 0.995` classified it a no-op, so the **source was copied through byte-for-byte unedited and the boundary reported `[cut] OK`**. That is §2's failure shape occurring inside the verifier. The copied artifact is verified on this path too, and the same stop-the-flow rule applies (it previously returned its report without gating on it). |
| a boundary check fails | **stop the flow**; never hand a corrupted artifact to the next stage |
| any tool exits non-zero | surface its stderr verbatim |
| **any tool exits zero but its artifact fails verification** | **fail** — this is the case §2 exists for |
| long operation interrupted | leave the last verified artifact in place; report which stage completed |
| **a required property is unreadable on this container** | **measure it, do not exempt it.** Measured, a fragmented `.mov` (what a crash-safe recorder writes) and a Matroska remux report `nb_frames=N/A` on every stream, and the cut boundary compares that number directionally — so a healthy recording was refused with `video.nb_frames: None -> 282`. `probe()` now counts the video stream's packets when the header omits the count. Costs, measured on real 1080p footage (88.6 s): `-show_streams` alone 0.03 s, `-count_packets` **0.05 s**, `-count_frames` **15.07 s** — so ~0.5 s versus ~122 s extrapolated to a 12-minute recording, for the same integer (7 of 7 files agreed across header / packets / frames). Still fails closed: an unreadable count stays `None` and refuses. |
| **paths the flow writes and removes** | `cut()` creates `<out>/`, **deletes** `<out>/<stem>_timeline.*` before exporting (so a stale EDL cannot be mistaken for the fresh one) and overwrites `<out>/<stem>_cut.mp4`. `caption()` creates `<project>/assets/` and **overwrites `<project>/assets/input.mp4`** inside the caller's project directory, then writes `<out>/<stem>_captioned.mp4`. All are by fixed name, so a re-run into a populated output directory overwrites its own prior outputs. **This is a description, not yet a policy** — nothing refuses to overwrite an artifact the flow did not create. Named here because it was unspecified entirely. |

---

## 6. Testing

**Fixtures are generated by ffmpeg at test time**, never committed — **and invalidated when the
ffmpeg that built them changes.** The first clause alone read as a hermeticity guarantee and was one
only for the first run on a clean tree: every generator returns early when its output exists, so a
fixture built under one ffmpeg survives the tool being upgraded and the suite keeps testing the old
tool's output while `cutline doctor` reports the new one. `tests/_fixtures/GENERATED-BY.txt` records
the building ffmpeg's version line; a mismatch **refuses**, naming both versions and the directory
to delete. It does not delete anything itself — a cache the operator did not ask to lose (the
`hfproj/` renders are minutes of work) is not the fixture's to throw away, and a refusal makes the
staleness a decision rather than an accident.

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
| **fragmented `.mov` with silence** | *(rev 4)* a container reporting **no `nb_frames` on any stream** — what a crash-safe recorder writes. Every fixture above is normally-muxed MP4 and reports a frame count, so none could reach the path where a directional property is compared against a value that could not be read. Built by `-c copy` remux of `silence_mid`, so the coded frames are identical and only the container's bookkeeping varies. |
| **variable frame rate, with silence** | *(rev 4)* `avg_frame_rate` genuinely diverging from `r_frame_rate`. §2 names phone footage as the ordinary input and it measurably is variable-rate: real Apple captures on this machine read `15/1` vs `711600/47429` and `30/1` vs `319080/10637`. The six original classes are all synthetic CFR at 30 fps, so the frame-count identity gate was green for want of a fixture that could reach it. |

**Positive control is required** and applies to the *fixture generator* as well as the detector: a
generator that cannot produce a dirty input has not shown the suite capable of red.

**Mutation check:** break the parser and the boundary comparator deliberately; the suite must go
red **against the fixtures above**, not merely against the happy path. Rev 4 added thirteen guards
and mutated each one: the frame counter, the no-op quantity, the source-bound EDL check, the profile
passthrough, the effects refusal, the stream-count classification, the CLI's `EdlError` catch, the
binary identification (**both directions** — the false negative it must catch and the false positive
it must not produce), both new fixture generators, and the `data-no-timeline` timing gate. All went
red; the log is in the review file's §7.

### CI

GitHub Actions on `ubuntu-latest` and `macos-latest`.

**ffmpeg is NOT preinstalled on either runner.** Rev 1 asserted it was; measured against both
runner-image manifests with positive controls, the string does not appear. CI must install it and
**pin the version**, or a runner-image bump reddens the suite with no code change — and green CI
would otherwise say nothing about the operator's ffmpeg 8.1.1 homebrew arm64 build.

**Rev 3, measured: "pin the version" is not satisfiable on the Linux runner with a distro
package, and the first attempt to satisfy it broke CI outright.** `ubuntu-latest` is Ubuntu 24.04,
which ships ffmpeg **6.1.1**; no Ubuntu release ships 8.x. A workflow step that ran
`apt-get install -y ffmpeg` and then asserted the major was `8` therefore failed on every run —
the exact failure mode the pre-flight rulings named, "CI red on a test that can never pass there
trains everyone to ignore CI".

CI currently asserts a **floor** of 6 plus the version-parsing surface, using
`cutline.tools.find_tool` so the check exercises the same parser the runtime does, and the step
name says floor rather than pin.

**What CI covers, and what it does not — measured against the workflow, not inferred.**
`.github/workflows/ci.yml` installs **neither auto-editor nor hyperframes** and runs
`pytest -m "not requires_auto_editor and not requires_hyperframes"`. That deselects **every test of
the cut stage, every test of the caption stage, and the CLI end-to-end test** — i.e. both of the two
handoffs cutline exists to verify. What CI proves green is probe, verify (on synthesised
`MediaInfo`), EDL parsing, fixture self-checks and tool discovery, on two ffmpeg builds. The
tool-boundary stages are exercised on **one machine on earth**, the operator's. Whether to install
those tools in CI is a scope decision for §7/§8; until it is taken, the closing claim below is
narrowed to what it earns.

**RESOLVED 2026-08-23 — measurement and ruling in §13.4.** `tools.FFMPEG_MIN` became
`tools.FFMPEG_FLOOR = "6"`: a real floor (version >= floor), not the prefix-equality series pin
`"8."` was silently being checked as. `find_tool` now takes an explicit `floor=` or `series=`
parameter instead of one ambiguous `min_version`, so the two semantics can no longer be confused
at the call site. `discover()` / `cutline doctor` now **accept** the runner's ffmpeg — measured
live in CI shipping **6.1.1** — where the old `"8."` prefix pin would have refused it, and would
equally have refused ffmpeg **9**, since prefix equality cannot express "at least." The CI step
itself now calls `find_tool(floor=FFMPEG_FLOOR)` directly rather than reimplementing the
comparison inline, so CI exercises cutline's own code path, not a parallel copy of it. **Green CI
now proves that ffmpeg discovery and cutline's pure layers hold on the runner it went green on** —
not that the pipeline does, since neither pipeline tool is installed there.

---

## 7. v1 scope

**In:** tool discovery and version pinning · `v3`/`v1` EDL parsing and validation · the full
`verify()` property set · a single orchestrated flow, *recorded* source: auto-editor cut →
verify → HyperFrames captions → verify · CLI · tests · CI.

**The cut's exposed parameters, with their defaults and the basis for them.** `--edit` (default
`audio`) and `--margin` (default `0.2sec`) are auto-editor's own defaults, passed through unchanged;
`cutline cut` exposes both. They decide whether the output is **usable** as opposed to merely
intact — a technically verified artifact with clipped word onsets satisfies every boundary check —
and until rev 4 the CLI exposed neither, so the only way to change a margin was to edit the source
while §0 celebrated asymmetric margins as a capability rev 1 lacked. **No basis has been measured for
the 0.2 s default on speech**; it is upstream's number, and §8's acceptance run is the first
opportunity to judge it.

**Input containers:** no precondition. A container that reports no per-stream frame count is
**measured** rather than refused (§5), so Matroska, fragmented `.mov` and streaming MP4 variants are
in scope. What is *not* in scope is any timeline carrying an effect (§3.1).

**Out:** recording, the faceless source path, MCP, GUI, publishing, thumbnails, any
reimplementation of a §3.2 upper-row capability.

The faceless path is deferred not because it is hard but because verifying one path properly
teaches what the second one needs.

### 7.1 First test subject

**`FORGE — Build 3 — 5-Threshold Content Series`, VIDEO 1 — THE EXPRESSION THRESHOLD.** A complete
8–15 minute solo direct-to-camera script that already exists in the vault, first in a five-part
series that has to be recorded regardless. Its own deployment notes call for 3–5 short clip
derivatives per video, which exercises the caption and reframe stages.

The Build 1 VSL is deliberately **not** first. It is a conversion asset; a pipeline should earn
trust on content before a money asset is run through it.

---

## 8. Roadmap and acceptance criteria

Each version is done when its criterion is met. Nothing is done by default.

| version | adds | done when |
|---|---|---|
| **v1** | verified recorded-source flow | a real recording goes cut → captioned, and **every boundary check the composite boundary actually gates on passes** — codec identity, a non-black render, stream counts, and at the cut boundary the full invariant set including rotation, geometry, profile and audio parameters; **the operator confirms the cut is USABLE**, not merely intact; the suite is proven able to go red against all **eight** fixture classes; **and a demonstrated RED** — a deliberately damaged artifact substituted at each boundary, which the boundary check rejects. |
| **v1.5** | own analyzer + renderer, as a *second* EDL producer behind the same interface — ⚠️ **contradicts §3.2's "out of scope in every version"; unresolved, see spec §8** | it renders the **first test subject** (spec §7.1), **preserves rotation**, and is benchmarked against auto-editor on the same file with the comparison published |
| v2 | faceless source path | a HyperFrames composition enters the same flow and passes the same boundary checks |
| v3 | MCP agent layer | an agent completes a full flow end to end, and **refuses** when a boundary check fails |
| v4 | recording, publishing | optional |

**Two clauses of the old v1 criterion were vacuous and are replaced above.** "Rotation verified"
was satisfiable by a check with no reachable failure state: at the cut boundary rotation is
invariant and §2 measured that it never changes, and at the composite boundary it is `may_change` by
measured design. And "the suite is proven able to go red" was, as §6 wrote it, a mutation of the
*comparator* — which proves the comparator is wired, not that a genuinely corrupted **output** is
caught. Every fixture in §6 is an INPUT; none is a damaged artifact. §2's `trim`/`concat` render is
the ready-made damaged artifact for the cut boundary.

⚠️ **§3.2 and the v1.5 row cannot both stand.** §3.2 says reimplementing a delegated capability is
"out of scope in **every version**", §11's first decision row is "orchestrate, don't reimplement",
and §0's headline is "cutline therefore orchestrates and verifies. It does not reimplement." v1.5
schedules an own analyzer **and** renderer — two upper-row capabilities — as the next milestone, with
acceptance criteria written as though the decision were already ratified. This is a governance
contradiction, not a runtime one, and resolving it is a scope decision rather than a wording fix:
either §3.2's absolute stands and v1.5 becomes "a second **external** EDL producer behind the same
interface", or §3.2 gains an explicit carve-out naming what would justify reimplementing — for which
§3.2's own last sentence ("the first question is whether to contribute it upstream") is the gate it
should have to pass first. **Flagged, not decided.**

**Not built, and named so it is not mistaken for shipped: a run provenance record.** A completed run
leaves artifacts and prints reports, and records nothing beside the output — not the tool versions,
the parameters, the EDL consumed, or the boundary reports. For a project whose thesis is provenance
(§0.1 makes "a figure must name the artifact it was read off" a standing rule for the *spec*), a
delivered video cannot answer "which auto-editor cut this, at what margin, and did its boundary
reports pass?" Deferred rather than built here because writing a sidecar beside the operator's output
is exactly the unspecified-write question §5's new row raises, and the two should be settled together.

---

## 9. Toolchain

`uv`, Python pinned `>=3.12`. System Python is 3.9.6 and is left untouched.

**auto-editor is installed from GitHub releases** (`auto-editor-macos-arm64`, tag `31.5.0`),
**never from pip** — see §0.2 and §5.

Measured install, 2026-08-22:

```
~/.local/bin/auto-editor            26,117,768 bytes
sha256  58d8893a389df60223b2a9d9f1307451d1581e1965c5f0e2e626c95024dbcca3
file    Mach-O 64-bit executable arm64
--version                           31.5.0
```

**Re-measured 2026-08-23: all four still hold.** The load-bearing one is `file` — §5's refusal
identifies the binary by *being a compiled image rather than a script*, which is the property that
separates this project from the pip one on every platform. The sha256 stays recorded as provenance
and is deliberately not enforced: it names one platform's asset.

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
| EDL format | consume auto-editor's `v3`, in **frames** (`v1` parsing is a scoped capability; the "cross-check" was never built — §3.1) | the producer already emits it; integer frame math avoids float drift | bound to its schema |
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

*(Rev 4: that last sentence was aspirational when written — §3.1's invariants were all properties of
the keep-list considered alone, so nothing was bounded by the source, and the retired arithmetic's
responsibility was inherited by no one. It is true now: §3.1 carries a source-bound invariant, and
`flow.cut` enforces it because the check needs a measured source length and so cannot live in a pure
parser.)*

---

## 13. Open questions

1. **auto-editor's real cut-count per hour of speech.** Unmeasured — no recording exists. It sizes
   nothing in v1 (render is delegated) but will size the flow's wall-clock.
2. ~~**Does auto-editor preserve rotation?**~~ **ANSWERED 2026-08-22 — yes.** Measured: rotation
   and geometry survive its render intact (§2). Separately measured: `--export otio` is **rejected**
   by the CLI — see §3.1. The render path, the one v1 depends on, is clear.
3. ~~**HyperFrames' caption stage as a boundary.**~~ **ANSWERED 2026-08-22.** It is a
   re-composite, not a passthrough: rotation is consumed, geometry becomes the canvas, duration
   becomes the composition's, and audio is silently resampled 44.1k/mono → 48k/stereo. Visual
   orientation is **correct** (verified by frame extraction against a reference). §2 and §4.1
   carry the detail and the corrected per-boundary policy. **Residual:** whether an unintended
   pillarbox should warn or fail is a judgement call, currently specified as *warn*.
4. ~~**Version-pin range policy** — exact pin or floor?~~ **ANSWERED 2026-08-23.** Rev 3 hit
   this in three places at once; each now has a shipped ruling:
   - **ffmpeg: a floor of 6.** **The inventory below was stale when written and is corrected here:
     `movie=` and `read_intervals` are both GONE** — `flow._sample_luma` replaced the `movie=` lavfi
     source with a plain `-i` argument and the 20-frame `read_intervals` probe with a whole-timeline
     `fps=` pass. **And it measures the wrong surface.** cutline's correctness does not rest on
     filter availability; it rests on **ffprobe's JSON schema** — that rotation is reachable in
     `side_data_list` with a stable key and sign, and that `nb_frames`, `nb_read_packets`,
     `sample_aspect_ratio` and `start_time` are reported the same way across the supported range.
     That surface has **not** been compared across versions: only ffmpeg 8.1.1 is installed here, the
     two CI legs run different builds (apt 6.1.1 on Linux, brew latest on macOS), and nothing in the
     suite asserts `probe()` equivalence across them. **The floor of 6 is therefore provisional in
     its justification even though the number is probably right.** Corrected inventory: cutline uses
     `signalstats`, `blackframe`, `metadata=print`, `fps=`, `-show_streams`, `-show_format`,
     `-count_packets` and `-select_streams` — nothing newer than roughly ffmpeg 3. The newest feature anywhere in the
     project is `-display_rotation`, which is **tests-only** (fixture generation in
     `tests/conftest.py`) and landed in ffmpeg 6.0 — hence a floor of 6, measured against the test
     suite rather than assumed from the runtime. `FFMPEG_MIN = "8."` (prefix equality, not a
     floor) is now `FFMPEG_FLOOR = "6"`, checked as a real floor by `find_tool(floor=...)`.
     `ubuntu-latest` was measured live in CI shipping **6.1.1**, which the old `"8."` prefix pin
     would have refused — and would equally have refused ffmpeg **9**, since prefix equality
     cannot express "at least" (§6, CI).
   - **auto-editor: exact `31.5.0`, unchanged.** The pin protects a measured export-format
     surface; that ruling was already settled and stays exact.
   - **hyperframes: the `0.8.` series, unchanged** — but not for the reason first given here. Not
     because two measurements once disagreed (a review-brief figure vs. this machine's output);
     that framing didn't survive a third data point. The actual reason: the version moves under us
     repeatedly and unattended — observed three times in one working day, 2026-08-22/23, on this
     same machine (see the comment above `HYPERFRAMES_SERIES` in `tools.py`) — which a series pin
     absorbs and an exact pin would not.

     **The pin is a proxy, not the guarantee.** What actually breaks cutline is a change in the
     render CLI's *shape* — the `render` subcommand, its cwd-relative output path,
     `assets/input.mp4`, the composition attribute vocabulary, `data-no-timeline` — not the version
     number. `tests/test_hyperframes_contract.py` is the real gate: one test per assumption,
     each diagnosable on its own, so a drift names what moved instead of "the render failed."
     `.github/workflows/upstream-check.yml` runs it weekly against `hyperframes@latest` and
     reports; it never bumps the pin itself.
5. **`COMPOSITE_POLICY.invariant` is a single property, `video.codec`. This is a v2 design item,
   not a v1 defect.** The caption stage's stop-the-flow gate is now under test (it was not, and
   could be deleted with the whole suite green), but even wired correctly it can only fire on a
   codec change — at the boundary §2 calls the suspect one. Everything else at that boundary is
   `may_change` or `warn`.

   **Measured, on the real acceptance artifact** (final review): the caption stage discards 3.4s of
   9.38s — **36% of the cut content** — and the boundary reports OK. Correct for a 6-second
   composition, but **indistinguishable from a renderer that dropped a third of the timeline**: a
   single-property invariant has no way to tell "the composition is short by design" from "the
   composition lost material it shouldn't have."

   **Not acted on here — v1 is not touched.** Two forward recommendations for whoever takes this up
   in v2:
   - **The cheap half:** move `video.width`/`video.height` from `may_change` to `warn`. Costs
     nothing, fails nothing, and makes a geometry surprise visible instead of silent.
   - **The real question, and it is design work, not a policy tweak:** what duration *should* the
     composite boundary assert against? Not the source's duration — the composite is expected to
     differ from that by construction — but the **composition's declared duration**, which nothing
     currently reads or checks. v2's faceless source path (§7, §8) runs a *different* composition
     through this same boundary, which is exactly where a single-property invariant starts costing
     something rather than merely looking thin.
6. **The black-frame gate AGGREGATES BY MEAN, so partial content loss is invisible.** Measured
   2026-08-23: a render whose first 25% is entirely black and whose remaining 75% is correct scores
   **0.2500** against the 0.80 gate — passes, reported OK. §4.1 carries the detail. The threshold
   discussion below is about *headroom*; the aggregation is the more consequential choice and was
   never discussed. Resolving it means stating a sustained-black RUN length, which is a number
   nothing has measured yet.

7. **The black-frame gate's threshold is measured against a 16:9 canvas only; v2 must re-measure
   against its own population.** `BLACK_FRAME_RATIO_THRESHOLD = 0.80` (`src/cutline/flow.py`) is
   measured, not assumed — but the measurement population is v1's, and v1 only exercises a 16:9
   canvas. **Measured:** a 2.35:1 source pillarboxed into a 9:16 canvas reaches **0.76** black-pixel
   ratio from legitimate letterbox bars alone — **0.04 of headroom** against the 0.80 gate, on
   content the gate is supposed to pass. v2's faceless source path composes into canvases v1 never
   tried; before that path relies on this gate, the threshold needs re-measuring against v2's own
   aspect-ratio population, not inherited from v1's.
