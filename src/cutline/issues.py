"""Content-issue DETECTION over a transcript. Reports; never edits.

This exists because of a measured failure in a tool that does the opposite.
On 2026-09-07 a third-party editor's transcript cleanup was run over the v1
acceptance recording. Its repeat-removal deleted 15 words for 6 reported
removals: every deletion took the FOLLOWING word with it, because a word
deletion becomes a time region and the region overran its neighbour.

    "where too much visibility attracted criticism"
        -> "where too much. attracted criticism"      ("visibility" gone)
    "rather than the full one"
        -> "rather than the one"                      ("full" gone)

Restoring was not possible either: restoring the pair and re-deleting only the
duplicate trimmed both again. And the restore verb reported `wordsRestored: 8`
while restoring 2, and destroyed 96 unrelated silence trims its own
documentation promised to leave untouched.

So this module detects and STOPS. It has no delete path, by construction --
not a flag, not a `--fix`, nothing. The operator rules on every candidate.
That is also what cutline is: it orchestrates and verifies, it does not author.

SEVERITY IS THE WHOLE DESIGN. The same measurement showed the expensive error
is not a missed repeat, it is a CONFIDENT WRONG ONE. The editor flagged this
line as a false start:

    "...and you delivered a softer version instead. Not because the softer
     version was more true. Because something calculated the risk..."

That is the speaker's script, verbatim -- deliberate parallel structure. Acting
on it would have destroyed the sentence. So a candidate whose restart DIVERGES
from the fragment is scored `low` and explicitly marked review-class, and only
`medium`/`high` set a non-zero exit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

# A repeat across a sentence boundary is usually real speech, not a stutter:
# "the behavioral exposure doesn't clear it. It just produces..." is correct
# English, and the measured tool cut "It just" out of the audio for it.
_SENTENCE_END = re.compile(r"[.!?]$")

# Repeating a stopword reads as a stutter far less often than repeating a
# content word ("the the" is noise; "visibility visibility" is a real re-take).
_STOPWORDS = frozenset([
    "a", "an", "the", "and", "or", "but", "so", "it", "its", "is", "was", "be", "been",
    "to", "of", "in", "on", "at", "for", "with", "that", "this", "these", "those", "i",
    "you", "he", "she", "we", "they", "me", "him", "her", "them", "my", "your", "our",
    "their", "as", "if", "then", "than", "not", "no", "yes", "do", "does", "did", "have",
    "has", "had", "will", "would", "can", "could"
])

_PUNCT = re.compile(r"[^\w']+")


def _norm(word: str) -> str:
    """Compare on letters only: 'because,' and 'Because' are the same word."""
    return _PUNCT.sub("", word).lower()


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Issue:
    kind: str          # adjacent-repeat | duplicate-take | false-start
    severity: str      # low | medium | high
    start: float
    end: float
    text: str
    note: str
    # The words a fixer WOULD remove -- surfaced so the operator can see the
    # blast radius of a decision this module deliberately refuses to make.
    candidate: str = ""

    def __str__(self) -> str:
        return (
            f"  {self.severity:<6} {self.kind:<16} {_ts(self.start)}  {self.text}\n"
            f"         {self.note}"
        )


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    @property
    def actionable(self) -> list[Issue]:
        """medium + high. `low` is review-class and never gates."""
        return [i for i in self.issues if i.severity in ("medium", "high")]

    @property
    def ok(self) -> bool:
        return not self.actionable

    def __str__(self) -> str:
        if not self.issues:
            return "[issues] none found"
        lines = [f"[issues] {len(self.issues)} candidate(s)"]
        for sev in ("high", "medium", "low"):
            for i in self.issues:
                if i.severity == sev:
                    lines.append(str(i))
        n_low = len(self.issues) - len(self.actionable)
        if n_low:
            lines.append(
                f"\n  {n_low} low-severity candidate(s) are REVIEW-CLASS and do not "
                "gate.\n  A restart that diverges from its fragment is usually "
                "deliberate parallel\n  structure, not a flub -- acting on one "
                "destroys the sentence."
            )
        lines.append("\n  Nothing was changed. This command has no edit path.")
        return "\n".join(lines)


def _ts(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


_SRT_TS = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = _SRT_TS.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(
            x.strip() for x in block[m.end():].strip().splitlines() if x.strip()
        )
        if body:
            cues.append(Cue(start, end, body))
    return cues


def _words(cues: Sequence[Cue]) -> list[tuple[str, float, float]]:
    """Flatten to (raw_word, start, end). Word times are interpolated across the
    cue by character weight -- an SRT is line-level by construction, so these
    are approximate and used only for REPORTING a location, never for editing."""
    out: list[tuple[str, float, float]] = []
    for c in cues:
        toks = c.text.split()
        if not toks:
            continue
        span = max(0.0, c.end - c.start)
        total = sum(len(t) for t in toks) or 1
        t = c.start
        for tok in toks:
            share = span * (len(tok) / total)
            out.append((tok, t, t + share))
            t += share
    return out


def _adjacent_repeats(words: Sequence[tuple[str, float, float]]) -> list[Issue]:
    issues = []
    for i in range(1, len(words)):
        prev_raw, _, _ = words[i - 1]
        cur_raw, s, e = words[i]
        a, b = _norm(prev_raw), _norm(cur_raw)
        if not a or a != b:
            continue
        crosses_sentence = bool(_SENTENCE_END.search(prev_raw))
        if crosses_sentence:
            sev = "low"
            note = ("repeat spans a sentence boundary -- often correct speech "
                    "(\"clear it. It just produces\"). Review before acting.")
        elif a in _STOPWORDS:
            sev = "low"
            note = "repeated stopword; usually a transcription artifact, not a re-take."
        else:
            sev = "medium"
            note = "content word repeated back to back; likely a stutter or re-take."
        ctx = " ".join(w for w, _, _ in words[max(0, i - 3):i + 3])
        issues.append(Issue("adjacent-repeat", sev, s, e, ctx, note, candidate=cur_raw))
    return issues


def _duplicate_takes(
    words: Sequence[tuple[str, float, float]], phrase: int, window: float
) -> list[Issue]:
    """A run of `phrase` words repeated within `window` seconds = a re-take.

    ...UNLESS the two occurrences DIVERGE afterwards. A re-take repeats a
    phrase AND carries on the same way; rhetoric repeats it and branches.

    That distinction is the whole guard, and it was learned the hard way: this
    detector scored the operator's own "it is not a confidence problem. It is
    not a fear of judgment problem." as `high` -- a confident wrong answer,
    the precise failure this module exists to avoid making.

    An earlier version of the guard required both occurrences to be
    sentence-INITIAL. It did not fire, because hers is preceded by a
    connective ("Because it is not a..."), and sentence position turned out to
    be a proxy for the thing that actually matters. Divergence is the thing
    itself, and it needs no sentence model at all.
    """
    issues = []
    seen = {}
    for i in range(len(words) - phrase + 1):
        key = tuple(_norm(w) for w, _, _ in words[i:i + phrase])
        if "" in key:
            continue
        start = words[i][1]
        if key in seen:
            prev_start, prev_i = seen[key]
            if start - prev_start <= window and i - prev_i >= phrase:
                nxt_a = (
                    _norm(words[prev_i + phrase][0])
                    if prev_i + phrase < len(words) else ""
                )
                nxt_b = (
                    _norm(words[i + phrase][0]) if i + phrase < len(words) else ""
                )
                diverges = nxt_a != nxt_b
                sev = "low" if diverges else "high"
                note = (
                    f"phrase repeats (first at {_ts(prev_start)}) but the two "
                    f"continue differently ({nxt_a!r} vs {nxt_b!r}) -- rhetoric "
                    "or parallel structure, not a re-take. REVIEW; do not auto-cut."
                    if diverges else
                    f"same {phrase}-word phrase already said at "
                    f"{_ts(prev_start)} ({start - prev_start:.1f}s earlier) and "
                    "continues the same way; likely a re-take. The LATER take is "
                    "usually the keeper."
                )
                issues.append(
                    Issue(
                        "duplicate-take", sev, start, words[i + phrase - 1][2],
                        " ".join(w for w, _, _ in words[i:i + phrase]), note,
                        candidate=" ".join(
                            w for w, _, _ in words[prev_i:prev_i + phrase]
                        ),
                    )
                )
        seen[key] = (start, i)
    return issues


# A false start is an ABANDONED attempt, so the fragment is short. Two long
# sentences sharing an opening are ANAPHORA -- a rhetorical device, not a flub.
# The operator's own script leans on it heavily ("Maybe you've been in a room...
# Maybe you've written something... Maybe you are walking around with..."), and
# a detector without this bound would flag every one of them.
_FRAGMENT_MAX_WORDS = 8


def _sentences(
    words: Sequence[tuple[str, float, float]]
) -> list[list[tuple[str, float, float]]]:
    out: list[list[tuple[str, float, float]]] = []
    cur: list[tuple[str, float, float]] = []
    for w in words:
        cur.append(w)
        if _SENTENCE_END.search(w[0]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _false_starts(
    words: Sequence[tuple[str, float, float]], prefix: int
) -> list[Issue]:
    """A SHORT sentence, then a next sentence that reopens the same way.

    Compares the two sentences' OPENINGS -- that is what a restart repeats.
    Scored `low` when the restart diverges after the shared prefix: that is the
    parallel-structure case, and acting on it destroys the sentence.
    """
    issues = []
    sents = _sentences(words)
    for a, b in ((sents[i], sents[i + 1]) for i in range(len(sents) - 1)):
        if len(a) > _FRAGMENT_MAX_WORDS:
            continue  # anaphora between full sentences, not an abandoned take
        if len(a) < prefix or len(b) < prefix:
            continue
        head = [_norm(w) for w, _, _ in a[:prefix]]
        tail = [_norm(w) for w, _, _ in b[:prefix]]
        if "" in head or head != tail:
            continue
        # Does the restart continue the SAME way, or branch off?
        nxt_a = _norm(a[prefix][0]) if len(a) > prefix else ""
        nxt_b = _norm(b[prefix][0]) if len(b) > prefix else ""
        diverges = nxt_a != nxt_b
        sev = "low" if diverges else "medium"
        note = (
            "restart DIVERGES from the fragment -- frequently deliberate parallel "
            "structure. REVIEW; do not auto-cut."
            if diverges else
            "restart reopens and continues the same way; likely an abandoned take. "
            "The LATER attempt is usually the keeper."
        )
        ctx = " ".join(w for w, _, _ in (a + b))
        issues.append(
            Issue("false-start", sev, a[0][1], b[-1][2], ctx, note,
                  candidate=" ".join(w for w, _, _ in a))
        )
    return issues


def find_issues(
    cues: Sequence[Cue],
    phrase: int = 4,
    window: float = 30.0,
    prefix: int = 2,
) -> Report:
    """Detect content issues. Pure: reads cues, returns a report, edits nothing."""
    words = _words(cues)
    issues = (
        _adjacent_repeats(words)
        + _duplicate_takes(words, phrase, window)
        + _false_starts(words, prefix)
    )
    issues.sort(key=lambda i: (i.start, i.kind))
    return Report(issues)


def find_issues_in_srt(text: str, **kw) -> Report:
    return find_issues(parse_srt(text), **kw)

