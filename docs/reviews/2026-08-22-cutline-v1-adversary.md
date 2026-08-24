# cutline v1 — Adversarial Review

**Subject:** `docs/specs/2026-08-22-cutline-v1-design.md`, rev 3
**Date:** 2026-08-23
**Reviewer stance:** skeptical senior engineer + product reviewer
**Verdict:** **REVISE**

---

## 0. How this review was conducted, and its limits

The spec is a design document for something it says is already implemented. A review of the
*text alone* would be theatre, so every claim below was checked against the artifact the spec
claims to describe: `src/cutline/{probe,verify,edl,tools,flow,cli}.py`, `tests/conftest.py`,
`.github/workflows/ci.yml`, `pyproject.toml`.

**This review executed nothing.** No ffmpeg, no ffprobe, no auto-editor, no CI run — the review
environment has no shell. Every finding is therefore one of two kinds, and each is labelled:

- **[TEXT]** — derived from what the spec and the code *say*. Certain, in the sense that the
  contradiction or gap is on the page.
- **[PREDICTED]** — a failure mode inferred from documented tool behaviour. Plausible, ranked as
  such, and listed again in §5 as something to measure before trusting.

The spec's own standing rule — a figure must name the artifact it was read off (§0.1) — applies to
reviews too. Nothing below is presented as measured that was not.

---

## 1. Verdict

**REVISE.**

The premise survives. "Orchestrate and verify, do not reimplement" is the right call, the rev-1
refutation was correct, and the rev-3 self-correction on provenance is the strongest single thing
in the document. This is not a STOP: nothing here says the architecture is wrong.

It is not a SHIP either, for one structural reason and several specific ones.

**The structural reason.** The spec's stated purpose is to be *the thing that catches a silently
wrong artifact* (§2). But §2 then measures that auto-editor preserves rotation, and §4.1 measures
that HyperFrames legitimately discards it. So at the only two boundaries v1 has, the headline
defect class is either **measured never to occur** (cut) or **permitted by policy** (composite).
The verifier as specified cannot fail on the defect it was built for. That does not make it
worthless — it is a regression net, and it demonstrably catches other things — but §8's v1
acceptance criterion, *"every boundary verified, including rotation on a portrait source"*, is
satisfiable by a check that has no reachable failure state. A criterion that cannot go red is not
a criterion. The spec needs to say what v1's verifier is actually *for* now that the measurements
moved the ground under it, and §8 needs a negative control rather than a positive one.

Below that: two correctness gates the spec asserts exist and that do not (F1, F2), a CI section
whose closing claim outruns what the workflow does (F4), and a set of EDL semantics the spec
consumes without ever defining (F2, F3).

None of these require redesign. All are spec-text changes measured in sentences.

---

## 2. Blockers

### F1 — §12 asserts a guard that §3.1 does not contain [TEXT]

**Severity:** blocker
**Sections:** §12 ("Not applicable after the pivot"), §3.1 ("Invariant enforcement moves to the
boundary")

§12 retires the margin-clamp arithmetic with this sentence: *"If auto-editor's margin handling
produces out-of-range segments, §3.1 catches it as input validation."*

§3.1 does not catch it. The invariants §3.1 names are ordering, positivity, non-overlap and
speed-vocabulary — all of them properties of the keep-list *considered alone*. "Out of range"
means out of range **of the source**, and §4 specifies the EDL module as **pure**. A pure parser
has no source duration, no frame count, and therefore no way to evaluate the predicate §12 relies
on. Confirmed in `src/cutline/edl.py:73-94`: `_validate` checks exactly the four properties above
and nothing bounded by the source.

**Failure mode.** A keep-segment with `offset + dur` past the last source frame parses clean,
validates clean, and reaches the render. Whatever auto-editor does with it — pad, truncate, error
— the cut boundary's only quantitative gate is a frame-count equality against that same EDL
(`flow.py:196`), so an EDL that over-claims and a render that pads to match it **agree**, and the
boundary reports OK.

**Why the existing text is not a guard.** §12 is the only place in the spec that assigns this
responsibility, and it assigns it to a section that structurally cannot discharge it. The retired
arithmetic was the previous owner; nothing inherited it.

**Smallest corrective change.** In §3.1, add a source-bound invariant to the named set — every
segment must end at or before the source's last frame — and state plainly that this one invariant
requires the source's measured length, so validation is *parse-pure plus one source-dependent
check*, not pure. Then §12's sentence becomes true instead of aspirational.

---

### F2 — §3.1 consumes `v3` without defining its semantics; `speed` is ungated in the primary format [TEXT]

**Severity:** blocker
**Sections:** §3.1, §4 (`edl.py` row)

§3.1 prints a `v3` clip — `{ "src", "start", "dur", "offset", "stream" }` — and never says what
any field means. It then says the internal model is "a keep-segment list in frames". Which of
`start` and `offset` indexes the output timeline and which indexes the source is left to the
reader. `edl.py:107` picks one reading; a second implementer, or the same one after a schema
change, has nothing to check that reading against.

More seriously: §3.1 gates the speed vocabulary **only for `v1`** — *"`v1` speeds other than
`1.0`/`99999.0` are legal and must be rejected explicitly in v1 scope"* — while naming `v3` the
**primary**. auto-editor supports speed changes in both. `parse_v3` (`edl.py:97-118`) reads
`start`, `dur`, `offset` and ignores everything else, including speed.

**Failure mode.** A source cut with any speed adjustment exports a `v3` timeline whose clips carry
a non-unit speed. Every clip parses as a keep. The keep-list's frame total is then a *source*
frame count while the render's frame count is a *time-scaled* one, so `_check_render_matches_edl`
— the spec's only truncation gate — fails with "the artifact is truncated or padded" on a render
that is perfectly correct. The secondary format is defended against a hazard the primary format is
wide open to.

**Why the existing text is not a guard.** §3.1's rejection rule is written in `v1`'s vocabulary
(`1.0` / `99999.0`) and scoped to `v1` by its own sentence. There is no general statement that
"any timeline feature outside v1 scope must be refused by name."

**Smallest corrective change.** In §3.1: (a) one sentence fixing the field semantics — which index
is the output timeline, which is the source, and that `dur` is source-frames; (b) restate the
scope gate format-independently: any clip carrying a speed other than unity, any timeline with more
than one video track or more than one `src`, is **refused by name** in v1, in `v3` as in `v1`.

---

### F3 — the frame-count gate assumes constant frame rate and a single timebase; §2 names variable-rate footage as the ordinary case [TEXT] + [PREDICTED]

**Severity:** blocker
**Sections:** §3.1 (units), §4.1 (frame count "catches truncation"), §6 (fixture set), §8 (v1
criterion)

§3.1 makes the correct argument for integer frame arithmetic and then leaves the load-bearing
assumption unstated: that the EDL's `timebase` and the source's actual frame cadence are the same
thing, and that both are constant.

§2 states the ordinary v1 input is **phone-shot portrait footage**. Phone capture is commonly
variable-frame-rate, and screen/webcam capture routinely is. For such a source, "frame count" is
not a stable quantity: `nb_frames` is a container-reported integer, the EDL's timebase is a
rational the exporter chose, and the render's cadence is whatever the renderer emitted.

**Failure mode.** Two, both silent in the spec:

1. **[PREDICTED]** VFR source, or a source whose fps does not equal the exported timebase (29.97
   source, `"30/1"` timebase). The EDL total and the rendered `nb_frames` are counted in different
   units. The equality gate then either fails on a correct render, or — with the no-op ratio
   (`flow.py:159`) computed across the same mismatch — misclassifies a real cut as a no-op and
   **copies the source through unedited while reporting `[cut] OK`**. That second one is the spec's
   own §2 failure shape: a tool reports success and the artifact is wrong.
2. **[TEXT]** §6's six fixture classes are all synthetic CFR at 30fps (`conftest.py:15`). The
   fixture set cannot produce the defect, so §8's "proven able to go red" says nothing about it.

**Why the existing text is not a guard.** §3.1 argues frames-over-seconds on *drift* grounds and
wins that argument; it never states the equivalence assumption the argument rests on. §6's fixture
table was built from the rev-1 defect list, which predates the frame-count identity gate.

**Smallest corrective change.** Two sentences. In §3.1: state that v1 requires the EDL timebase to
match the source's measured average frame rate and refuses when it does not, and that VFR sources
are **out of v1 scope until measured**. In §6: add a seventh fixture class — a variable-rate source
— or, if that is deferred, say explicitly in §7 ("Out") that VFR input is unsupported in v1, so the
gap is a declared boundary rather than an unexamined one.

---

### F4 — CI installs neither tool whose boundary the spec exists to check, and §6's closing claim does not say so [TEXT]

**Severity:** blocker
**Sections:** §6 (CI), §8 (v1 criterion)

§6's CI subsection is entirely about ffmpeg. It closes: *"Green CI now proves cutline would run on
the runner it went green on."*

Measured against the workflow: `.github/workflows/ci.yml:71-86` installs neither auto-editor nor
hyperframes and runs `pytest -m "not requires_auto_editor and not requires_hyperframes"`. Per
`pyproject.toml:37-41` and the marker sweep across `tests/`, that deselects **every test of the cut
stage, every test of the caption stage, and the CLI end-to-end test**. What remains green is
probe, verify (on synthesised `MediaInfo`), EDL parsing, fixture self-checks and tool discovery.

**Failure mode.** The two handoffs that constitute the product — the two boundaries §3 draws, the
two policies §4.1 distinguishes at length — are exercised on exactly one machine on earth, the
operator's. A regression in `flow.cut` or `flow.caption` reaches `main` green. The
`_check_render_matches_edl` claim ("measured across all six fixture classes, delta 0 in every
case") is re-verified by nothing on any schedule.

**Why the existing text is not a guard.** §6 makes a version-scoped claim about ffmpeg and then a
much broader closing claim about "cutline" that the version-scoped work does not support. The
deselection is documented in a workflow comment, not in the spec. A reader of the spec has no way
to learn that CI's coverage stops at the tool boundary.

**Smallest corrective change.** In §6, one honest paragraph: name what CI covers and what it does
not, state that the tool-boundary stages are verified only by an operator-local run, and narrow the
closing claim to what it earns — that ffmpeg discovery and the pure layers hold on both runners.
If tool-boundary coverage in CI is wanted, that is a scope decision for §7/§8, not a wording fix;
either way the spec should stop implying coverage it does not have.

---

### F5 — the acceptance criterion has no negative control, so v1 can be declared done without the verifier ever having fired [TEXT]

**Severity:** blocker
**Sections:** §8 (v1 row), §4.1, §6 (mutation check)

§8 declares v1 done when *"a real recording goes cut → captioned with every boundary verified,
including rotation on a portrait source; the suite is proven able to go red against all six
fixture classes."*

Both halves are weaker than they read.

- **"rotation verified" is vacuous at both boundaries.** At the cut boundary rotation is invariant
  and §2 measured it never changes. At the composite boundary rotation is `may_change` by measured
  design (§4.1 table). Passing the criterion demonstrates that nothing which was never going to
  happen did not happen.
- **The mutation check tests the comparator, not the pipeline.** §6 says *"break the parser and the
  boundary comparator deliberately."* Breaking the comparator proves the comparator is wired.
  It does not prove that a **genuinely corrupted artifact** — the §2 trim/concat output the spec
  holds positive proof of — is caught, because no fixture in §6 is a corrupted *output*. Every
  fixture is an input.

**Why the existing text is not a guard.** §13.5 sees the adjacent problem (a one-property composite
invariant) and defers it to v2, while §8 continues to describe the same boundary as "verified".
The two sections disagree about what the word means, and §8 is the one that gates release.

**Smallest corrective change.** Add one clause to §8's v1 row: the criterion also requires a
**demonstrated red** — a deliberately damaged artifact substituted at each boundary (the §2
trim/concat render is the ready-made one for the cut boundary) which the boundary check **rejects**.
And replace "every boundary verified, including rotation" with what the composite boundary actually
gates on today (codec identity, non-black render, declared audio parameters), so the criterion
states the truth §13.5 already admits.

---

## 3. High

### F6 — `start_time` was added to the checked set but never classified per boundary; the drift it exists to catch is silently permitted [TEXT]

**Severity:** high
**Sections:** §4.1 (property table and per-boundary table), §6

Rev 3 spends its longest correction on divergent stream `start_time` and states the consequence
precisely: *"cuts computed on the audio timeline and applied to the video timeline drift by that
offset."* The per-boundary policy table immediately below it has four columns — rotation, geometry,
duration, audio params. `start_time` is in neither column nor a fifth. `verify.py:133-134` resolves
the ambiguity the only way an unclassified property can be resolved: `may_change`, no direction
constraint, at the cut boundary.

**Failure mode.** The property is read and discarded. More fundamentally, the spec has filed it in
the wrong place: a source whose streams diverge is a **pre-condition of the input**, not a delta
across a handoff. Comparing before-offset to after-offset cannot detect the hazard, because the
hazard is that the offset existed *at all* when the cut was computed. As specified, a source with a
half-second audio lead is processed without comment.

**Why the existing text is not a guard.** §4.1's property table is a list of things to *read*; the
per-boundary table is the list of things to *rule on*. `start_time` appears only in the first.

**Smallest corrective change.** In §4.1, give `start_time` a row in the per-boundary table, and add
one sentence stating that a source whose video and audio `start_time` diverge beyond a stated
threshold is reported **before the cut runs**, as an input pre-condition — not as a boundary delta.
State the threshold, or state that it is unmeasured and provisional.

---

### F7 — "stream count + kinds" is named as a checked property and is not expressible in the property model the same section defines [TEXT]

**Severity:** high
**Section:** §4.1

The property table's fourth row is *"stream count + kinds | catches a dropped audio track."* The
model §4.1 then builds addresses properties as `video.*` and `audio.*` — singular. `verify.py:46-52`
enumerates one video stream and one audio stream; `probe.py:42-48` resolves those as *first of
kind*. There is no property in the model whose value is "how many streams, of what kinds."

**Failure mode.** A two-language recording (two audio tracks) or a source with an attached
subtitle/data stream passes through a stage that drops the second track. Every named property of
the *first* audio stream is identical. The report reads OK. This is the §2 shape exactly — a
handoff loses content while every assertion still passes — for the one property §4.1 says catches
a dropped audio track.

**Why the existing text is not a guard.** The row exists; the model beneath it silently narrows to
first-of-kind, and no sentence reconciles them.

**Smallest corrective change.** In §4.1, state that stream count and the ordered list of stream
kinds are themselves a checked property, classified per boundary like any other — or, if v1 means
to support single-video/single-audio sources only, say so as a precondition in §7 and delete the
row. Either is honest; the current pairing is not.

---

### F8 — §3.1 promises the EDL as a "declared expectation"; §4's verifier structurally cannot consume it, and nothing else in the spec places that check [TEXT]

**Severity:** high
**Sections:** §3.1 (closing paragraph), §4 (`verify.py` interface)

§3.1: *"`v3` also carries `resolution`, `samplerate` and `layout` — precisely the properties
`verify()` needs, so the EDL doubles as a **declared expectation** to check the rendered artifact
against."*

§4 gives `verify.py` the signature `MediaInfo, MediaInfo, Policy → Report`. There is no parameter
through which a declared expectation can arrive. The promise is unwired at the level of the type,
not the implementation — and the implementation confirms it: `edl.py` parses `resolution`,
`sample_rate` and `layout` into `Edl` and no module reads them back. The one expectation check that
does exist (frame count, `flow.py:196`) was bolted into the orchestrator, not the verifier.

This matters most at the composite boundary, where §4.1's own second question is *"are the output
audio parameters the **declared** ones, rather than whatever the renderer chose?"* — a question the
spec asks, has the data to answer, and provides no place to answer it.

**Why the existing text is not a guard.** §3.1 and §4 were written in different passes and neither
references the other's shape.

**Smallest corrective change.** In §4, state that boundary verification takes an optional declared
expectation alongside the two `MediaInfo`s, and that a render disagreeing with its own EDL's
declared resolution / sample rate / layout is a boundary failure. One sentence, and §3.1's promise
becomes locatable.

---

### F9 — §3.2 forbids in every version what §8 schedules for v1.5 [TEXT]

**Severity:** high
**Sections:** §3.2, §8 (v1.5 row), §11 (build vs adopt)

§3.2 assigns "silence / motion / black / subtitle cutting" and "render" to auto-editor and closes:
*"Reimplementing anything in the upper rows is out of scope in **every version**."* §11's first
decision row: *"orchestrate, don't reimplement."*

§8's v1.5 row: *"own analyzer + renderer, as a second EDL producer behind the same interface."*

That is a reimplementation of two upper rows, scheduled as the **very next milestone** after the
release whose entire thesis is that it must never happen. This is not a nuance; it is the document
contradicting its own headline (§0: *"cutline therefore orchestrates and verifies. It does not
reimplement."*).

**Failure mode.** Not runtime — governance. The rev-1 → rev-2 pivot's whole value was a scope
boundary that holds under pressure. A boundary with a dated exception one milestone out is a
boundary that will not survive the first inconvenience, and the portfolio claim in §1
("integration architecture, *not* a reimplementation of a solved problem") is undercut by the
roadmap on the same page.

**Why the existing text is not a guard.** §8's v1.5 row carries acceptance criteria (renders §7.1,
preserves rotation, published benchmark) which read as if the decision were already ratified. Nothing
in §3.2 or §11 acknowledges the exception exists.

**Smallest corrective change.** Pick one and write it down. Either §3.2's absolute stands and v1.5
is deleted or restated as "a second *external* EDL producer behind the same interface" — or v1.5 is
kept and §3.2 gains an explicit carve-out naming what would justify reimplementing (a measured
upstream deficiency, upstream contribution attempted first per §3.2's own last sentence). The
current pair cannot both be true.

---

### F10 — v1 depends on `nb_frames`, which the primary recorder's default containers do not populate [TEXT] + [PREDICTED]

**Severity:** high
**Sections:** §3 (architecture: OBS), §4.1, §7.1, §8

Two v1 gates depend on ffprobe reporting a frame count: the no-op short-circuit (`flow.py:158-159`)
and the EDL/render agreement check (`flow.py:217-224`, which fails closed and calls the cut
unverifiable when the count is absent).

The project already knows this field is not universal — `tests/test_verify.py:156` carries the
comment *"ffprobe does not report `nb_frames` for every container."* The spec does not. It names
OBS as the v1 recorder (§3, §7.1) and states no requirement on the container OBS is configured to
write.

**Failure mode [PREDICTED].** Matroska, and fragmented/streaming MP4 variants, commonly report no
per-stream frame count without an explicit counting pass. On such a source: the no-op check is
skipped silently (`source_frames` falsy), and then the agreement check refuses outright — so the v1
acceptance run of §7.1 terminates with "the render reports no frame count" on a completely healthy
recording. This is exactly the §6-CI failure mode the spec names elsewhere: red on something no code
change can fix.

**Why the existing text is not a guard.** §5's error table has no row for "a required property is
unreadable on this container", and §7/§7.1 state no input format precondition.

**Smallest corrective change.** In §7, add an input precondition: v1 requires a source container
for which ffprobe reports a per-stream frame count, and name the recording configuration that
satisfies it. Add a row to §5 for the unreadable-property case, stating that it fails closed and
what the operator should change. (Recounting frames explicitly is a design option, not a spec fix —
flag it, don't specify it here.)

---

### F11 — the pip-detection rule is specified by outcome only, and the spec records a hash it never requires anyone to check [TEXT]

**Severity:** high
**Sections:** §5 ("auto-editor installed from pip"), §9

§5 says *"fail loudly — detect and refuse"* and specifies no detection method. §9 records exactly
the material that would make detection sound — a 26,117,768-byte Mach-O arm64 binary and its
sha256 — and never requires it to be used. The implementation's chosen method
(`tools.py:183`: a file named `python` next to the binary) is both:

- **false-positive-prone**, and precisely where the spec sends people: §9 installs the *correct*
  Nim binary to `~/.local/bin/auto-editor`, a directory that very commonly also holds a `python`
  shim. The good install is refused as a bad one.
- **false-negative-prone**: a pip install into any layout without that sibling passes the check and
  is then caught only by the version pin — which is a *different* refusal with a *different*
  message, so the operator is told "wrong version" for a problem that is "wrong project."

**Why the existing text is not a guard.** "Detect and refuse" delegates the hard part to the
implementation, and §9's hash sits in the document as provenance rather than as a rule.

**Smallest corrective change.** In §5, state the detection *criterion* rather than the outcome:
the binary is identified positively — by executable format, and by hash where a release asset is
pinned — and anything failing that identification is refused as "not the pinned release," one
message, one failure mode. §9 already holds the values; it needs a sentence saying they are load-
bearing.

---

### F12 — the ffmpeg floor was measured against filters and flags, not against ffprobe's output schema, and §13.4's inventory is already stale [TEXT]

**Severity:** high
**Sections:** §6 (CI), §13.4 (first bullet)

§13.4 justifies the floor of 6 by inventorying what cutline uses: *"`signalstats`, `blackframe`,
`metadata=print`, `movie=`, `read_intervals`, `-show_streams` and `-show_format`."*

Two problems.

1. **The inventory does not match the code it claims to be measured from.** `movie=` and
   `read_intervals` are both gone — `flow.py:246-267` documents replacing the `movie=` lavfi source
   with a plain `-i` argument, and replacing the 20-frame `read_intervals` probe with a whole-
   timeline `fps=` pass. A measurement that names artifacts no longer present is the exact defect
   §0.1 was written to stamp out, reappearing in the section that answers the question §0.1's
   discipline was invoked for.
2. **The inventory measures the wrong surface.** cutline's correctness does not rest on filter
   availability; it rests on **ffprobe's JSON schema** — specifically that rotation is reachable in
   `side_data_list` with a stable key and sign, and that `nb_frames`, `sample_aspect_ratio` and
   `start_time` are reported the same way across the supported range. That is the surface the floor
   should have been measured against, and it was not.

Compounding it: the two CI legs do not run the same ffmpeg (`ci.yml:20-28` — apt on Linux, brew
latest on macOS), and the operator runs a third. Nothing in the suite asserts that `probe()` returns
equivalent values across them.

**Failure mode [PREDICTED].** A side-data key, or a rotation sign convention, that differs between
ffprobe 6 and 8 makes `rotation` read `None` — or the negated value — on one leg. Since `None` is a
legitimate value meaning "absent" (`probe.py:65-74`, deliberately, and correctly), a version that
reports it differently produces a rotation check that passes for the wrong reason on one platform.

**Why the existing text is not a guard.** §13.4 is presented as a resolved, measured ruling, which
discourages exactly the re-examination it needs. The floor may well still be 6; the *justification*
is measuring something else.

**Smallest corrective change.** In §13.4, re-scope the first bullet: state that the floor is
measured against ffprobe's reported schema for the §4.1 property set, not against filter
availability, and name the versions the schema was compared across. Correct the stale filter list.
In §6, state that the supported ffmpeg range is covered by at least one test asserting `probe()`
equivalence — or state that it is not, and that the range is provisional.

---

### F13 — §6's fixture doctrine has no invalidation rule; fixtures persist across runs and across tool versions [TEXT]

**Severity:** high
**Sections:** §6 (opening line), §4.1 / §0.1 (the `offset_streams.mp4` provenance)

§6: *"Fixtures are generated by ffmpeg at test time, never committed."*

They are generated **once** and then cached on disk indefinitely. `conftest.py:26-46` is explicit
and alarmed about it — *"Editing this function's ffmpeg args has NO EFFECT until the matching file
is deleted"* — and records a live case where a mutation check passed against a stale cached fixture
and had to be re-run. Every other generator in the file repeats the same `if out.exists(): return`.

The spec says none of this. And the caching interacts with the two findings above: a fixture built
under one ffmpeg persists after the tool is upgraded, so the suite silently keeps testing the old
tool's output while `doctor` reports the new tool. The rev-3 provenance correction itself rests on
a re-measurement of a cached file (`§0.1`, `§4.1`) whose generating ffmpeg version is not recorded
anywhere.

**Why the existing text is not a guard.** "Generated at test time, never committed" reads as a
hermeticity guarantee and is one only for the *first* run on a clean tree. CI gets that guarantee;
the operator's machine — the only place the tool-boundary stages are exercised at all (F4) — does
not.

**Smallest corrective change.** In §6, replace the one-line doctrine with two: fixtures are
generated, never committed, **and invalidated whenever the generator or the ffmpeg version that
built them changes**. State that the ffmpeg version used to build a fixture is recorded alongside
it, so a measurement quoted from a fixture (§4.1's `0.476009`) names the tool that produced it —
which is §0.1's own rule applied one level down.

---

## 4. Medium and low

### F14 — the black-render gate averages, so it can only detect *mostly* black [TEXT] — medium
**Sections:** §4.1 (third composite question), §13.6

§4.1's third composite check is *"is the visual content actually present, rather than a
correctly-sized black frame?"* The gate is a **mean of per-frame black-pixel ratio across the
timeline** (`flow.py:276-280`). A render whose first quarter is black and whose remainder is
correct averages to roughly a quarter of the black frames' ratio — comfortably under the threshold,
reported OK. §13.6 discusses the threshold's *headroom* against legitimate letterboxing and never
the *aggregation*, which is the more consequential choice: partial content loss is both more likely
than total loss and entirely invisible to a mean.

**Corrective:** in §4.1, state the check as "no sustained black run exceeding a stated duration",
not "the render is not black on average", and note the threshold in §13.6 governs the per-frame
ratio, not the aggregate.

### F15 — §5 gives the empty EDL two contradictory behaviours and no exit path [TEXT] — medium
**Section:** §5

Two adjacent rows: *"EDL fails an invariant → fail with the offending segment printed"* and *"EDL is
empty, or keeps ≈ 100% of source → short-circuit, exit explaining why."* Empty and keeps-everything
are **opposite** conditions collapsed into one row with one behaviour — one means "nothing was cut,
don't re-encode", the other means "everything was cut, there is no output." The implementation
resolves it as an invariant failure (`edl.py:80-81`), which the CLI does not catch
(`cli.py:64` handles `FlowError`/`ToolError`/`FileNotFoundError`; the EDL error is a `ValueError`),
so the specified "exit explaining why" is [PREDICTED] a traceback. That is a legitimate real input:
a recording that is silence end to end.

**Corrective:** split the row. Empty EDL is its own condition with its own message; keeps ≈ 100% is
the no-op copy. State the exit code for each.

### F16 — the `v1` "cross-check" is promised and never located [TEXT] — medium
**Sections:** §3.1, §4, §7

§3.1 and §11 both say cutline consumes `v3` *"with `v1` as a cross-check."* No section says when the
cross-check runs, what is compared, or what a disagreement means. §4's `edl.py` row parses both;
§7's scope line says "`v3`/`v1` EDL parsing and validation" — parsing, not cross-checking. Nothing
in the flow invokes it. A cross-check that exists nowhere in the architecture is a claim, not a
control. **[PREDICTED]:** whether auto-editor's `v1` export even carries the `timebase` key the
parser requires is unverified here; if it does not, the path raises on every real export.

**Corrective:** either place it in §4 (which stage runs it, on what, and that a disagreement stops
the flow) or drop the phrase from §3.1 and §11 and keep `v1` parsing as scoped capability only.

### F17 — the silence-detection knobs are unspecified, unreachable, and unrecorded [TEXT] — medium
**Sections:** §3.2, §4 (`cli.py` row), §7.1, §8

The spec delegates silence detection entirely and then never states the parameters it delegates
*with*. auto-editor's edit expression and threshold, and the margin, determine whether the output is
usable; the implementation fixes them at `--edit audio` and `--margin 0.2sec` (`flow.py:99`) and the
CLI exposes neither (`cli.py:57-66`). §0 celebrates asymmetric margins as a capability rev 1 lacked;
nothing plumbs them.

The product consequence: §8's v1 criterion is met by a *technically* verified artifact with clipped
word onsets. "Verified" and "usable" are different claims and the spec only makes the first.

**Corrective:** in §7, name the edit mode, threshold and margin as v1's exposed parameters with
their defaults and the basis for them; in §8, add an editorial acceptance clause to the v1 row — the
operator confirms the cut is usable, not merely intact.

### F18 — no run provenance record, in a project whose thesis is provenance [TEXT] — medium
**Sections:** §4, §8, §0.1

A completed run leaves artifacts and prints reports. Nothing records, with the artifact: the tool
versions used, the parameters, the EDL consumed, the boundary reports. §0.1 elevates "a figure must
name the artifact it was read off" to a standing rule for the *spec*; the *pipeline* has no
equivalent, so a delivered video cannot answer "which auto-editor cut this, at what margin, and did
its boundary reports pass?" For a portfolio artifact about verification across tool boundaries, this
is the most visible omission in the document.

**Corrective:** in §4, state that each run emits a provenance record beside its output carrying tool
versions, parameters, the EDL, and every boundary report; in §8, make its presence part of the v1
criterion.

### F19 — no policy on destructive writes or re-runs [TEXT] — medium
**Section:** §5

The flow deletes files matching a glob in the caller's output directory (`flow.py:134`), overwrites
`assets/input.mp4` inside the caller's project directory (`flow.py:324`), and overwrites its own
outputs by fixed name. All are defensible; none is specified. §5's table covers tool failures and
verification failures and says nothing about what the flow is permitted to destroy, or whether a
re-run into a populated output directory is safe.

**Corrective:** add a row to §5: which paths the flow writes, which it removes, and that it refuses
rather than overwrites an artifact it did not create.

### F20 — duration is compared for exact equality with a one-directional constraint and no tolerance [TEXT] + [PREDICTED] — medium
**Section:** §4.1 (cut row: "may shrink")

"May shrink" is implemented as strict `after > before → failure` (`verify.py:174-186`). At a
boundary that **re-encodes audio**, output duration can exceed input duration by an encoder's
priming/padding — tens of milliseconds — independent of how much video was cut. **[PREDICTED]** on a
short derivative clip (§7.1 calls for 3–5 per video) with a small cut, that padding can exceed the
removed duration and fail a correct render with "this boundary permits a shrink, not a growth."

**Corrective:** in §4.1, state the tolerance — duration may grow by at most one frame plus one audio
frame — or state that duration is diagnostic at this boundary and the frame-count/EDL agreement is
the gate.

### F21 — §4's component table does not match the shipped CLI [TEXT] — low
**Section:** §4 (`cli.py` row)

§4 lists `probe · verify · cut · caption · run`. The binary offers `doctor · probe · cut · caption ·
run` (`cli.py`): `verify` is specified and absent, `doctor` ships and is unspecified — while §6 and
§13.4 both refer to `cutline doctor` as though §4 had introduced it.

**Corrective:** correct the row.

### F22 — the no-op short-circuit is an unstated exception to "a boundary check fails → stop the flow" [TEXT] — low
**Section:** §5

The short-circuit path returns its boundary report without gating on it (`flow.py:162-170`), so a
failing report on that path is printed and exits zero. Harmless today — the path is a byte-for-byte
copy, so the report cannot fail — but §5 states the stop-the-flow rule without exception, and an
unstated exception is how a real one gets added later.

**Corrective:** one clause in §5's short-circuit row: the copied artifact is still verified and the
same stop-the-flow rule applies.

---

## 5. Enhancements — explicitly *not* blockers

These are worth doing and none of them should hold a release.

- **§13.5's "cheap half"** — moving composite geometry from `may_change` to `warn`. The spec already
  reasons it through and defers it correctly. Agreed with the deferral.
- **§13.6's threshold re-measurement for v2** — correctly scoped to the version that needs it. The
  aggregation problem (F14) is the part that is *not* a v2 concern.
- **§11's adaptive render finding** — well recorded, correctly parked. The 3.9% keyframe-snap drift
  noted there is the number that will matter if v1.5 proceeds; it deserves to be carried into
  whatever resolves F9.
- **Upstream contribution path** — §3.2's *"the first question is whether to contribute it
  upstream"* is excellent and appears exactly once. If F9 resolves toward keeping v1.5, this
  sentence is the gate it should have to pass first.

---

## 6. Verdict summary

| # | Severity | Section(s) | One line |
|---|---|---|---|
| F1 | blocker | §12, §3.1 | §12 delegates an out-of-range guard to a section that structurally cannot perform it |
| F2 | blocker | §3.1 | `v3` field semantics undefined; `speed` gated only in the secondary format |
| F3 | blocker | §3.1, §6, §8 | frame-count identity assumes CFR + matching timebase; §2's ordinary input may be neither, and no fixture covers it |
| F4 | blocker | §6, §8 | CI installs neither tool; both product boundaries are untested, and §6's closing claim implies otherwise |
| F5 | blocker | §8, §4.1, §6 | acceptance criterion has no reachable failure state and no negative control |
| F6 | high | §4.1 | `start_time` checked but unclassified; it is an input pre-condition, filed as a boundary delta |
| F7 | high | §4.1 | "stream count + kinds" is named and is not expressible in the model beneath it |
| F8 | high | §3.1, §4 | the EDL-as-declared-expectation promise has no parameter to arrive through |
| F9 | high | §3.2, §8, §11 | §3.2 forbids in every version what §8 schedules as the next milestone |
| F10 | high | §3, §7, §5 | two v1 gates depend on `nb_frames`; no input-container precondition is stated |
| F11 | high | §5, §9 | pip-detection specified by outcome only; §9's hash is recorded and not required |
| F12 | high | §6, §13.4 | floor measured against filters, not ffprobe's schema; the inventory is stale |
| F13 | high | §6 | fixtures persist across runs and tool versions; the doctrine has no invalidation rule |
| F14 | medium | §4.1, §13.6 | black-render gate averages, so partial content loss is invisible |
| F15 | medium | §5 | empty EDL: two contradictory behaviours, no exit path |
| F16 | medium | §3.1, §4 | the `v1` cross-check is promised and never located |
| F17 | medium | §7.1, §8, §4 | silence/margin parameters unspecified, unreachable, unrecorded; "verified" ≠ "usable" |
| F18 | medium | §4, §8 | no run provenance record, in a project whose thesis is provenance |
| F19 | medium | §5 | no policy on destructive writes or re-runs |
| F20 | medium | §4.1 | exact-equality duration with a directional constraint and no tolerance |
| F21 | low | §4 | component table does not match the shipped CLI |
| F22 | low | §5 | no-op short-circuit is an unstated exception to stop-the-flow |

**Blockers are 5 of 22, and every one of them is a text change measured in sentences.** None asks
for a redesign; all five ask the spec to state something it currently implies, or to stop implying
something it has not earned. That is why the verdict is REVISE and not STOP.

---

## 7. Working notes, uncertainties, and what needs real-environment validation

**Method.** Read the spec end to end, then read every module, the test conftest, the CI workflow and
the packaging metadata, and cross-examined each spec claim against the artifact it describes. The
highest-yield technique was the one rev 3 invented on itself: for each measured claim, ask *which
file was this read off, and is that file still what the sentence says it is.* F12 and F13 both fell
out of that question.

**Doubt — what this review could not do.** No execution. No ffmpeg, ffprobe, auto-editor,
hyperframes or CI run was performed; the review environment has no shell. Every [PREDICTED] label
above marks an inference from documented tool behaviour that I could not confirm here, and the
severity assigned to it is my estimate of its likelihood, not a measurement.

**Claims requiring real-environment validation before acting on them:**

1. **F10 — `nb_frames` on the operator's actual recording container.** Record one short clip with
   OBS as it is configured today, run ffprobe, and check whether `nb_frames` is populated on the
   video stream. This is a two-minute measurement that decides whether F10 is a blocker for the
   §7.1 acceptance run or a non-issue. Do this one first.
2. **F3 — VFR.** Whether the intended §7.1 source is constant or variable rate, and whether
   auto-editor's exported `timebase` equals the source's measured frame rate on that file. If both
   are clean, F3 downgrades to "state the assumption" rather than "add a fixture."
3. **F12 — ffprobe schema across the supported range.** Run `probe()` against the same rotated
   fixture under ffmpeg 6.1.1 and 8.1.1 and compare the returned rotation value **including sign**.
   I could not confirm the sign convention; §2's tables say `90` while `-display_rotation 90` is
   commonly reported by ffprobe as `-90`, which may be a real inconsistency in the spec's tables or
   may simply be this ffmpeg's convention. Worth ten minutes either way.
4. **F2 / F16 — auto-editor's actual export shapes.** Whether a speed-adjusted timeline appears in
   `v3` clips as a `speed` field, and whether the `v1` export carries `timebase` at all. Both are
   single `--export` invocations against an existing fixture.
5. **F20 — audio padding.** Cut a 20-second clip with a ~0.5% removal and compare input and output
   `format.duration`. If the output is longer, F20 is live today rather than predicted.

**One thing I want to flag that is not a finding.** The spec is unusually honest — §0.1's
self-correction, §13.5's admission that a gate it shipped is thin, §6's account of breaking CI and
why. That honesty is what made this review possible at the depth it reached: almost every blocker
above was reachable *because* the document says enough to be checked. The failure mode this
document is now most exposed to is not dishonesty; it is **claims that were true when written and
quietly stopped being true** — F12's stale inventory and F13's stale fixtures are both that shape.
If one process change comes out of this review, make it that: a measured claim carries the artifact
*and* the date it was read, and anything older than the code it describes is re-read before it is
cited again.

---

# 7. Measurement pass — 2026-08-23

*Added by the recording-readiness pass. The review above executed nothing and said so; this section
is the measuring. Every row names a command that was actually run. Where a finding was refuted, the
refuting command is recorded so nobody re-derives the prediction. Where a finding survived, the fix
and the mutation that proved the new guard can go red are named.*

**Environment.** macOS arm64 · ffmpeg/ffprobe **8.1.1** (homebrew) · auto-editor **31.5.0** (Nim,
`~/.local/bin`, sha256 and byte size re-measured against §9 and unchanged) · hyperframes **0.8.10** ·
Python 3.12.13 via `uv`. Suite before: **94 passed / 254.9 s**. After: **109 passed / 180.2 s**.

## 7.1 What a real recording actually did

The single highest-yield measurement was one the review could not take and the brief did not ask
for: put a **real Apple-written `.mov`** through `flow.cut()`. Two files were available on this
machine (88.6 s 1080p and 79.0 s, both rotated portrait capture). Results, all new:

| observed | consequence |
|---|---|
| `video.profile` **Main → High** | **the cut was refused on a healthy render.** Not in the review. Fixed by declaring the source's profile to auto-editor's `-profile:v`; measured, the same file then rendered Main with an identical frame count. |
| `rotation` reported **`-90`** | §2's tables say `90`. cutline is unaffected (it compares, never interprets) but the spec's tables were wrong about sign for real capture. F12's open sign question, answered. |
| `avg_frame_rate` **≠** `r_frame_rate` (`711600/47429` vs `15/1`; `319080/10637` vs `30/1`) | F3's premise confirmed on real material: phone capture *is* variable-rate. |
| **four and five streams** — (audio, video, data, data) | F7's hazard confirmed on real material; auto-editor drops the `data` streams. |
| `nb_frames` **present** on both files | F10's *premise* narrowed — see below. |
| video and audio `start_time` **both `0.000000`** | retires §4.1's standing "UNMEASURED" on real recorders. |

## 7.2 Per-finding verdicts

| # | verdict | how it was measured | disposition |
|---|---|---|---|
| **F1** | **CONFIRMED** | `parse_v3` on a `v3` declaring one 999999-frame keep against a 90-frame source → parsed clean, `total_frames=999999` | source-bound invariant added in `flow._check_edl_fits_the_source`, bounded on **timeline** frames; `edl.parse` stays pure. **M3** red. |
| **F2** | **CONFIRMED, and the mechanism is not what was predicted** | `auto-editor --set-speed 2.0,0,1.5sec --export v3` → the clip carries `"effects": ["speed:2.0"]`, **not** a `speed` field; `parse_v3` ignored it | refused by name, fail-closed on any effect. **M5** red, with a negative control on a plain export. |
| F2's *predicted failure mode* | **REFUTED** | rendered the same speed timeline: **68 frames, EDL total 68** — `dur` counts OUTPUT frames, so `_check_render_matches_edl` does not misfire | recorded in `edl.Keep`'s docstring and spec §3.1 |
| **F3** | **CONFIRMED** | real capture measured VFR (above); all six original fixtures are synthetic CFR 30 fps | seventh + **eighth** fixture classes added (`fragmented_source`, `variable_frame_rate`), each with a positive control. **M8**, **M9** red. A VFR source now cuts and verifies. |
| **F4** | **CONFIRMED** | read `.github/workflows/ci.yml`: installs neither tool, runs `pytest -m "not requires_auto_editor and not requires_hyperframes"` | spec §6 now names what CI covers and what it does not; the closing claim narrowed. Installing the tools in CI left as a scope decision. |
| **F5** | **CONFIRMED** | §8's criterion read against §4.1's own tables: rotation is invariant-and-never-changes at cut, `may_change` at composite | §8 rewritten: states what the composite boundary actually gates on, requires a **demonstrated red** at each boundary, and adds the usability clause |
| **F6** | **CONFIRMED** | `verify.py:133` — `start_time` sits in `may_change` with no direction, and appears in no per-boundary column | given a per-boundary column; the input-pre-condition check **not built** — the threshold has no measured population (one synthetic file at 0.476009, two real captures at 0.000000) |
| **F7** | **CONFIRMED** | `verify(two-audio, one-audio, CUT_POLICY)` → `ok=True`; real capture carries 4–5 streams | `video_streams` / `audio_streams` are checked properties, invariant at cut (measured: 1→1, 2→2), warn at composite. **M6** red. |
| **F8** | **CONFIRMED** | `inspect.signature(verify)` → no expectation parameter; `grep` → nothing reads `Edl.resolution / sample_rate / layout` back | spec §4 states which half is wired (profile, outbound) and which is not (EDL-declared resolution/rate/layout). Not built. |
| **F9** | **CONFIRMED** | §3.2 vs §8's v1.5 row, read side by side | governance contradiction; **flagged in §8 and in the roadmap row itself, not decided** — it is a scope call |
| **F10** | **CONFIRMED, premise narrowed** | `cut()` on a fragmented `.mov` → `video.nb_frames: None -> 282`. Same on a Matroska remux. **But** both real Apple `.mov` files DO report `nb_frames`, and QuickTime Player's own container could not be measured without recording | `probe()` counts packets when the header omits the count. **M1** red. See 7.3 for the residual. |
| **F11** | **CONFIRMED, both directions** | put a `python` beside a symlink to the genuine binary → **the good install was refused**; measured pipx and uv console scripts are `#!` text while the release is Mach-O | replaced with positive identification. **M11** (false negative) and **M11b** (false positive) both red. |
| **F12** | **CONFIRMED (inventory + surface); sign question ANSWERED; cross-version UNVERIFIED** | `grep` → `movie=` and `read_intervals` are gone from the source; rotation measured `-90` on real capture | §13.4's inventory corrected, the justification re-scoped to ffprobe's schema and marked provisional. **Cross-version `probe()` equivalence could not be measured — only ffmpeg 8.1.1 is installed here.** |
| **F13** | **CONFIRMED** | `conftest.py` — every generator returns early on `out.exists()`, with no version stamp anywhere | `tests/_fixtures/GENERATED-BY.txt`; a mismatch **refuses**, naming both versions and the directory to delete. Verified red by editing the stamp. |
| **F14** | **CONFIRMED, with a number** | built a render 25% black / 75% correct → `black_pixel_ratio = 0.2500` against the 0.80 gate: **passed** | recorded in §4.1 and §13.6 as a known blind spot. Not changed: a sustained-run length is a number nothing has measured. |
| **F15** | **[TEXT] CONFIRMED; [PREDICTED] traceback REFUTED** | `cutline cut` on an all-silence source → auto-editor exits 1 with `Error! Timeline is empty, nothing to do.`, surfaced verbatim, clean exit 1 — **no traceback** | §5's row split into two. `EdlError` is nonetheless now caught by the CLI: it subclasses `ValueError`, escapes as a traceback, and F2's new refusal makes that path reachable. **M7** red. |
| **F16** | **[TEXT] CONFIRMED; [PREDICTED] REFUTED** | `--export v1` → the export **does** carry `"timebase": "30/1"`; and nothing anywhere invokes `parse_v1` as a cross-check | the "with `v1` as a cross-check" claim withdrawn from §3.1, §11 and the README rather than left reading as a shipped gate |
| **F17** | **CONFIRMED** | `cli.py` exposed neither `--margin` nor `--edit`, which `flow.cut()` has always taken | both exposed, upstream defaults unchanged. §7 names them and admits **no basis is measured for 0.2 s on speech**. |
| **F18** | **CONFIRMED** | nothing is written beside an output but the artifact | **not built** — a sidecar beside the operator's output is exactly F19's unspecified-write question; named in §8 so it is not mistaken for shipped |
| **F19** | **CONFIRMED** | `flow.py` — one glob unlink, two `copyfile`s into caller-owned directories, fixed output names | §5 now enumerates every path written and removed, and states plainly that a refuse-rather-than-overwrite policy does **not** exist yet |
| **F20** | **CONFIRMED, then the CAUSE removed rather than tolerated** | `cut()` on a fragmented `.mov` → `duration: 3.066667 -> 3.088254`, a **+0.0216 s growth**. After the F10 and no-op fixes, the same input short-circuits to a byte copy and **every** duration across six containers shrank | **no tolerance added.** A one-frame bound (0.0333 s at 30 fps) would not have covered the measured population anyway — a second container grew **+0.0418 s**. Residual named in §4.1: `verify()` is public and still exact. |
| **F21** | **CONFIRMED** | `grep '@app.command'` → `doctor · probe · cut · caption · run`; §4 listed `verify` and omitted `doctor` | §4's row corrected |
| **F22** | **CONFIRMED** | `flow.py` — the short-circuit returned its report without gating on it | gated. Deliberately **not** mutation-tested: the path is a byte-for-byte copy, so the report has no reachable failure state today; the guard exists so a future reachable one is not silently exempt. |
| **NEW — no-op unit mismatch** | **CONFIRMED — a live silent-wrong-artifact bug** | source with 6 s video / 12 s audio and real silence: EDL kept **281 of 360** timeline frames, `281 >= 180 × 0.995` classified it a no-op, **the source was copied through byte-identical and the boundary reported `[cut] OK`** (md5 equal) | the gate now compares timeline frames to timeline frames. **M2** red. This is F3's predicted failure-mode 1 arriving by a different route than predicted. |
| **NEW — `video.profile`** | **CONFIRMED on real footage** | see 7.1 | `flow._profile_args`. **M4** red. |
| **NEW — csv trailing comma** | **CONFIRMED, caught by its own new control** | the first draft of the packet counter used `-of csv=p=0` and returned `None` on every file carrying side data (`"360,"` parses as no integer) — i.e. exactly the rotated sources §2 is about | switched to `-of json`; the control test caught it on its first run |

## 7.3 What could not be verified, and what is still open

1. **QuickTime Player's own container shape is UNMEASURED.** The brief's premise is that QuickTime
   writes crash-safe (fragmented) `.mov`, which is why `nb_frames` would be absent. Measuring it
   requires making a recording, which needs the operator. What *was* measured: two real
   Apple-written `.mov` files on this machine both **do** report `nb_frames`; the QuickTime Player
   container holds no autosave data to inspect; and its binary yields no conclusive evidence. **The
   fix does not depend on which way this goes** — an absent count is now measured rather than
   refused, and a present one is used as before. That is deliberate: the unknown was removed from
   the path rather than resolved by betting on it.
2. **ffprobe schema equivalence across the supported ffmpeg range is UNVERIFIED.** Only 8.1.1 is
   installed here. F12's recommendation stands unactioned and §13.4 now says the justification is
   provisional.
3. **`verify()`'s exact float duration comparison** is left as a contract question (F20 above).
4. **§3.2 vs the v1.5 roadmap row** (F9) is a scope decision, flagged in two places and not taken.
5. **F6's input pre-condition, F8's EDL-declared expectation, F14's aggregation, F18's provenance
   record** are all confirmed and all deliberately unbuilt — each needs a number or a contract
   nobody has measured or ratified. Every one is named in the spec at the place a reader would
   look for it, rather than left implied.
