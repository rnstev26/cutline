# cutline v1 — Design

**Date:** 2026-08-22
**Status:** Ratified. Implementation plan pending.
**Scope:** v1 only. Later versions are sketched in §9 to show the seam holds, not to specify them.

---

## 1. Purpose

Produce a polished talking-head video from a raw recording by removing dead air, and prove the
result on disk rather than reporting success from an exit code.

The driving need is video for the Sovereign SOUL and Sovereign Systems funnels — non-faceless,
recorded, currently low volume and rising. A secondary and explicit goal is that the repository
serve as an applied-AI-engineering portfolio artifact.

### What this is not

HyperFrames already covers generated faceless brand content, and it composites *on* footage —
captions, overlays, graphic cards — but it does not *cut* footage. Neither does Remotion. That
gap, `record + cut`, is what `cutline` addresses. Captions are deliberately out of v1 scope
because HyperFrames already does them well and locally.

---

## 2. Architecture: the EDL is the seam

One intermediate representation. Every module is a producer or a consumer of it.

```
   [producers]              [the seam]            [consumers]

 silence analysis ──┐                         ┌──→ render  (ffmpeg)
 transcript   (v2) ─┼──→    EDL (JSON)   ─────┼──→ captions (v2)
 human editor (v3) ─┘       keep-segments     └──→ probe / report
```

The EDL is a list of **keep**-segments, not cut-segments. Keeps render by direct concatenation;
cuts would require inversion at every consumer.

```json
{
  "source": "raw.mp4",
  "duration": 612.4,
  "keeps": [
    { "start": 0.0,  "end": 12.3 },
    { "start": 14.9, "end": 31.2 }
  ]
}
```

**Why this matters:** the alternative — functions that take an MP4 and return an MP4 — discards
the decisions that were made, leaving the interesting behaviour untestable. Writing the decisions
down makes the analysis layer assertable without rendering anything, which is what keeps the test
suite fast.

**Invariants**, enforced in `edl.py` and property-tested:

1. `keeps` is sorted by `start`
2. no two keeps overlap
3. every keep satisfies `0 <= start < end <= duration`
4. `keeps` may be empty (a recording that is entirely silence is a valid, if useless, result)

---

## 3. Components

Each module has one job and an interface that can be described without reference to its internals.

| module | responsibility | interface | depends on |
|---|---|---|---|
| `edl.py` | the seam: model, JSON round-trip, invariant enforcement, operations (`total_duration`, `apply_margin`) | pure functions + dataclasses | nothing |
| `probe.py` | ffprobe wrapper → `MediaInfo`; `verify()` for assertions | `Path → MediaInfo` | ffprobe |
| `analyze.py` | source → EDL. v1 producer: `silencedetect` | `Path, SilenceParams → EDL` | ffmpeg, `edl` |
| `render.py` | EDL + source → MP4, one ffmpeg pass | `Path, EDL, Path → Path` | ffmpeg, `edl` |
| `cli.py` | `probe` · `analyze` · `render` · `cut` | typer | all of the above |

`edl.py` holding the most logic while having zero I/O is deliberate: the component most likely to
harbour subtle bugs is the one with the fastest and most reliable tests.

### 3.1 `analyze.py` — silence detection

v1 uses ffmpeg's `silencedetect` filter:

```
ffmpeg -i <source> -af silencedetect=n=<noise>dB:d=<min_duration> -f null -
```

The filter writes `silence_start` / `silence_end` pairs to stderr. `analyze` parses those,
**inverts them into keep-segments**, and applies a margin so cuts do not clip the beginnings and
ends of words.

Defaults, to be tuned against real recordings, not guessed at permanently:

| parameter | default | meaning |
|---|---|---|
| `noise` | `-30dB` | threshold below which audio counts as silence |
| `min_duration` | `0.5s` | shortest silence worth cutting |
| `margin` | `0.15s` | padding retained on each side of a keep |

**Open risk, named:** `silencedetect` is confirmed present in ffmpeg 8.1.1 on the target machine
but has **not** been proven against real speech — the available test render had no audio track.
The first test written is that proof. If the filter behaves poorly on real voice recordings, this
assumption changes and the finding is recorded rather than tuned around.

### 3.2 `render.py` — EDL to MP4

A single `ffmpeg -filter_complex` invocation: `trim` + `atrim` per keep-segment, then `concat`.

Re-encoding is unavoidable — cut points do not fall on keyframes — so stream copying is not an
option. This is a single pass, not a two-step segment-then-concat, which avoids temporary files
and keeps the operation atomic.

An empty EDL is an error at the render boundary, not a zero-length MP4.

---

## 4. Error handling

| condition | behaviour |
|---|---|
| `ffmpeg` / `ffprobe` absent | fail at startup with the missing binary named, not a stack trace |
| source file missing or unreadable | fail before invoking any subprocess |
| source has no audio stream | fail explicitly — silence analysis is meaningless without audio |
| `silencedetect` yields no silence | valid result: a single keep spanning the whole source |
| EDL violates an invariant | raise at construction, never at render time |
| empty EDL passed to render | error, naming the EDL as the cause |
| ffmpeg exits non-zero | surface ffmpeg's stderr; never report success |
| ffmpeg exits zero but produces no/short artifact | **fail** — verified by probe, per §5 |

The last row is the one that matters. A media tool that trusts an exit code will eventually report
a successful render of nothing.

---

## 5. Testing

The test strategy is a designed part of this system, not an afterthought.

**Fixtures are generated at test time by ffmpeg.** A sine tone with silence gaps at *known*
timestamps, plus a colour-source video track. No committed binaries, no Git LFS; the repository
stays text-only and the tests stay hermetic and fast.

**Assertions run on ffprobe output of real artifacts.** The code under test produces a real file
and the test measures that file. Mocking the subprocess would only prove the mock behaves as
written.

**Positive control is required.** A detector is only trusted once it has been shown able to
produce both answers:

- a fixture with silence at known timestamps → those timestamps must be found, within tolerance
- a fixture with continuous audio → must return no silence

A clean result from an instrument never shown capable of a dirty one is not evidence.

**Mutation check.** Before the suite is trusted, the timestamp parser is deliberately broken and
the suite must go red. A green suite that cannot go red is not testing anything.

**Property tests** cover the EDL invariants in §2.

Tests that shell out to real binaries carry the `requires_ffmpeg` marker so they can be
deselected where no ffmpeg exists.

### CI

GitHub Actions, on `ubuntu-latest` **and** `macos-latest`. ffmpeg is installed on the runner.
Both `ruff` and `pytest` must pass. Two platforms because ffmpeg's stderr formatting is the
parsing surface, and it is not guaranteed identical across builds.

---

## 6. Repository layout

```
cutline/
  pyproject.toml  .python-version   uv-managed, Python pinned >=3.12
  README.md  LICENSE  NOTICE        Apache-2.0
  src/cutline/
    edl.py  probe.py  analyze.py  render.py  cli.py
  tests/
    conftest.py                     fixture generators
    test_edl.py  test_probe.py  test_analyze.py  test_render.py  test_cli.py
  spikes/auto-editor-comparison/    throwaway, see §8
  .github/workflows/ci.yml
  docs/specs/                       this document
```

---

## 7. Toolchain

`uv` manages the project and its Python. The system Python on the target machine is 3.9.6 —
below this project's floor — and is deliberately left untouched.

`auto-editor` is **not** a v1 dependency (see §8).

---

## 8. The auto-editor spike — throwaway

The original plan named `auto-editor` as v1's analyzer. On design review it was found that
`ffmpeg -af silencedetect` covers v1's entire scope using a dependency already required for
rendering, while `auto-editor` would add a second toolchain whose distinctive value — motion
detection and NLE round-trip export — is out of v1 scope.

Rather than decide by preference, v1 ships on `silencedetect` and a **separate throwaway spike**
compares both producers on the same real recording. The comparison decides v2's producer by
measurement.

**The spike is explicitly not part of the product.** It lives in `spikes/`, its output is
gitignored, and nothing in `src/` may import from it.

**It is blocked** until a real speech recording with natural pauses exists. It does not block v1.

A version discrepancy is noted and unresolved: PyPI reports `auto-editor` 29.3.1 while the GitHub
release listing indicated 31.0.2. Whichever actually installs is what gets recorded.

---

## 9. Iteration path

Sketched to demonstrate the seam holds. Not specified here.

| version | adds | shape |
|---|---|---|
| **v1** | silence cut, verified render, CLI, tests, CI | *this spec* |
| v2 | `whisper-cli` → word-level JSON; filler-word cutting; captions via HyperFrames | one producer, one consumer |
| v3 | MCP server — the agent layer | consumer of the same core |
| v4 | recording, or handoff to OpenCut for a GUI | optional |

MCP lands at v3 deliberately. A tested deterministic core comes first; the agent surface is built
over something already proven. Building the conversational layer over untested internals would
put the outworking before the inworking.

**Explicitly not in v1:** whisper, captions, recording, MCP, GUI, publishing.

---

## 10. Decisions and their reasoning

| decision | choice | why |
|---|---|---|
| shape | deterministic core + later agent layer | core is testable in isolation; agent layer is additive |
| runtime | Python | matches existing body of work; the lane Applied AI Engineer roles hire into |
| seam | EDL of keep-segments | makes analysis assertable without rendering |
| v1 analyzer | ffmpeg `silencedetect` | zero new dependencies; auto-editor's advantages are out of v1 scope |
| auto-editor | throwaway spike | decides v2's producer by measurement rather than preference |
| licence | Apache-2.0 | express patent grant; matches HyperFrames upstream |
| fixtures | generated at test time | hermetic tests, text-only repository |
| verification | ffprobe the artifact | an exit code is not evidence a file exists |

---

## 11. Open questions

1. **`silencedetect` on real speech** — unproven. First test resolves it. May change §3.1's defaults.
2. **Silence thresholds** — the §3.1 defaults are starting points, to be tuned against real recordings and re-recorded here once measured.
3. **auto-editor version** — PyPI and GitHub disagree; resolved at install.
4. **Margin semantics** — whether margin should be symmetric or asymmetric (speech tends to need more lead-in than lead-out) is unresolved and worth measuring in the spike.
