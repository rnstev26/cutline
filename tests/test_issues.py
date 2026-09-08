"""Detection-only content issues.

The expensive error here is not a missed repeat -- it is a CONFIDENT WRONG one.
So most of these assert RESTRAINT: that a legitimate construction is either not
flagged, or flagged `low` and kept out of the gate.
"""

from __future__ import annotations

import cutline.issues as issues_mod
from cutline.issues import Cue, find_issues, find_issues_in_srt, parse_srt


def _srt(*blocks: str) -> str:
    out = []
    for i, (start, end, text) in enumerate(blocks, 1):
        out.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(out)


def test_clean_transcript_reports_nothing():
    cues = [Cue(0.0, 3.0, "There is a specific kind of silence that does not come from")]
    assert len(cues[0].text.split()) > 4, "precondition: enough words to scan"
    r = find_issues(cues)
    assert r.issues == [], r
    assert r.ok


def test_repeated_content_word_is_medium_and_gates():
    r = find_issues([Cue(0.0, 4.0, "where too much much visibility attracted criticism")])
    hits = [i for i in r.issues if i.kind == "adjacent-repeat"]
    assert hits, "precondition: the repeat must be detected at all"
    assert hits[0].severity == "medium", hits[0]
    assert not r.ok, "a content-word stutter should gate"


def test_repeat_across_a_sentence_boundary_is_low_and_does_not_gate():
    """'doesn't clear it. It just produces...' is correct English.

    The measured third-party tool cut 'It just' out of the audio for this.
    """
    r = find_issues([Cue(0.0, 5.0, "the exposure does not clear it. It just produces more")])
    hits = [i for i in r.issues if i.kind == "adjacent-repeat"]
    assert hits, "precondition: it IS a surface-level repeat, so it must be seen"
    assert hits[0].severity == "low", hits[0]
    assert r.ok, "a sentence-boundary repeat must never gate"


def test_repeated_stopword_is_low():
    r = find_issues([Cue(0.0, 4.0, "rather than the the full one and nothing else")])
    hits = [i for i in r.issues if i.kind == "adjacent-repeat"]
    assert hits, "precondition: repeat present"
    assert hits[0].severity == "low", hits[0]


def test_repeated_phrase_within_the_window_is_a_high_duplicate_take():
    text = ("this is the part I want to say this is the part I want to say again")
    r = find_issues([Cue(0.0, 8.0, text)])
    dups = [i for i in r.issues if i.kind == "duplicate-take"]
    assert dups, "precondition: a 4-word phrase does repeat here"
    assert dups[0].severity == "high", dups[0]
    assert not r.ok


def test_anaphora_is_not_a_high_duplicate_take():
    """REGRESSION, found by running this detector on the operator's real ASR.

    "Because it is not a confidence problem. It is not a fear of judgment
     problem." -- the repeated opening is her rhetoric. Before the guard this
    scored `high` and would have gated: a confident wrong answer, the exact
    failure this module exists to avoid.
    """
    text = (
        "Because it is not a confidence problem. It is not a fear of judgment "
        "problem. It is something more specific than both of those."
    )
    r = find_issues([Cue(0.0, 12.0, text)])
    dups = [i for i in r.issues if i.kind == "duplicate-take"]
    assert dups, "precondition: the 4-word phrase genuinely does repeat"
    assert all(d.severity == "low" for d in dups), dups
    assert "not a re-take" in dups[0].note
    assert r.ok, "anaphora must never gate"


def test_a_real_retake_still_scores_high_even_at_a_sentence_start():
    """The guard must not blunt the detector: same opening, same continuation."""
    text = "So the point I want to make. So the point I want to make is simple."
    r = find_issues([Cue(0.0, 8.0, text)])
    dups = [i for i in r.issues if i.kind == "duplicate-take"]
    assert dups, "precondition: the phrase repeats"
    assert any(d.severity == "high" for d in dups), dups
    assert not r.ok, "a genuine re-take must still gate"


def test_repeat_outside_the_window_is_not_a_duplicate_take():
    """Same phrase an hour apart is a callback, not a re-take."""
    cues = [
        Cue(0.0, 3.0, "this is the part I want to say"),
        Cue(600.0, 603.0, "this is the part I want to say"),
    ]
    assert cues[1].start - cues[0].start > 30, "precondition: outside the window"
    dups = [i for i in find_issues(cues).issues if i.kind == "duplicate-take"]
    assert dups == [], dups


def test_the_operators_real_parallel_structure_never_gates():
    """REGRESSION. Her script, verbatim:

        "...you delivered a softer version instead. Not because the softer
         version was more true. Because something calculated the risk..."

    A third-party detector flagged this as a false start. Acting on it would
    have destroyed the sentence. It must be low at most, and must not gate.
    """
    text = (
        "and you delivered a softer version instead. Not because the softer "
        "version was more true. Because something calculated the risk of the "
        "accurate one."
    )
    r = find_issues([Cue(0.0, 12.0, text)])
    assert len(text.split()) > 20, "precondition: the full construction is present"
    assert r.ok, f"her deliberate parallel structure must NOT gate: {r}"
    for i in r.issues:
        assert i.severity == "low", i


def test_false_start_that_CONTINUES_the_same_way_is_medium():
    """A real abandoned take: the restart reopens AND carries on identically."""
    r = find_issues([Cue(0.0, 6.0, "I want to. I want to talk about something else")])
    fs = [i for i in r.issues if i.kind == "false-start"]
    assert fs, "precondition: a repeated opening after a sentence end exists"
    assert fs[0].severity == "medium", fs[0]
    assert not r.ok, "a genuine abandoned take should gate"


def test_false_start_that_DIVERGES_is_low_review_class():
    """Parallel structure, not a flub -- the exact shape a fixer must not cut.

    ("one for transcription, one for outreach" is the canonical example.)
    """
    r = find_issues([Cue(0.0, 6.0, "One for transcription. One for outreach and more")])
    fs = [i for i in r.issues if i.kind == "false-start"]
    assert fs, "precondition: the openings DO match, so it is seen"
    assert fs[0].severity == "low", fs[0]
    assert "REVIEW" in fs[0].note or "review" in fs[0].note
    assert r.ok, "a diverging restart must never gate"


def test_anaphora_between_full_sentences_is_not_a_false_start():
    """REGRESSION. The operator's script leans hard on anaphora:

        "Maybe you've been in a room where... Maybe you've written something..."

    Both sentences open identically. Neither is an abandoned take, and a
    detector that flags them is useless on this speaker's material.
    """
    text = (
        "Maybe you have been in a room where the unsoftened version of your "
        "opinion was sitting in your chest. Maybe you have written something "
        "that was fully you and then revised it down before you sent it."
    )
    r = find_issues([Cue(0.0, 14.0, text)])
    starts = [i for i in r.issues if i.kind == "false-start"]
    assert text.count("Maybe you have") == 2, "precondition: the anaphora is present"
    assert starts == [], f"anaphora must not be flagged: {starts}"


def test_low_only_report_is_ok_but_still_lists_the_candidates():
    r = find_issues([Cue(0.0, 5.0, "does not clear it. It just produces more of it")])
    assert r.issues, "precondition: something WAS found"
    assert r.ok, "low-only must not gate"
    assert "REVIEW-CLASS" in str(r), str(r)


def test_report_says_nothing_was_changed():
    r = find_issues([Cue(0.0, 4.0, "where too much much visibility attracted criticism")])
    assert r.issues, "precondition: an issue exists to report"
    assert "Nothing was changed" in str(r)


def test_module_exposes_no_edit_path_at_all():
    """Structural guarantee, not a promise in prose.

    The tool this replaces deleted 15 words for 6 reported removals. The
    protection here is that there is no code path to delete anything -- so
    assert the module surface stays detection-only.
    """
    banned = [
        n for n in dir(issues_mod)
        if any(k in n.lower() for k in ("delete", "remove", "fix", "apply", "write"))
    ]
    assert banned == [], f"issues.py must stay detection-only; found {banned}"


def test_srt_round_trip_gives_timed_cues():
    text = _srt(
        ("00:00:01,000", "00:00:03,000", "where too much much visibility attracted"),
    )
    cues = parse_srt(text)
    assert len(cues) == 1, "precondition: the SRT parsed"
    assert cues[0].start == 1.0 and cues[0].end == 3.0, cues[0]
    r = find_issues_in_srt(text)
    assert any(i.kind == "adjacent-repeat" for i in r.issues), r
    assert 1.0 <= r.issues[0].start <= 3.0, "issue must locate inside its cue"
