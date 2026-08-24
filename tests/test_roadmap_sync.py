import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_roadmap_sync import roadmap_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/specs/2026-08-22-cutline-v1-design.md"


def test_readme_and_spec_roadmaps_agree():
    readme = roadmap_rows(ROOT / "README.md")
    spec = roadmap_rows(SPEC)
    assert readme, "no roadmap rows found in README — the parser or the doc changed shape"
    assert spec, "no roadmap rows found in the spec — the parser or the doc changed shape"
    assert readme == spec, f"roadmap drift:\n README {readme}\n SPEC   {spec}"


def test_rows_carry_the_whole_row_not_just_the_version_label():
    """The guard used to extract only `(v[0-9.]+)` from column 1 and compare
    that. Measured in review: rewriting the README's v1 row — "adds" to
    `TOTALLY DIFFERENT SCOPE`, "done when" to "nothing at all, ship it blind" —
    left it printing `roadmap in sync` and exiting 0.

    The assertion is on CELL STRUCTURE plus one phrase from each of columns 2
    and 3, not on the criterion's wording. It used to pin the literal string
    "rotation on a portrait source", and when the adversarial review's F5
    established that that clause was vacuous — rotation is invariant at the cut
    boundary and `may_change` at the composite one, so it named a check with no
    reachable failure state — this test went red on the CORRECTION. A guard
    that reddens when the thing it guards is improved is asserting a revision,
    not a behaviour: the behaviour here is "columns 2 and 3 survive the
    extractor", and any phrase from them proves it.
    """
    rows = roadmap_rows(ROOT / "README.md")
    v1 = next(r for r in rows if r.startswith("v1 |"))
    assert len(v1.split(" | ")) == 3, v1
    assert "verified recorded-source flow" in v1          # column 2
    assert "a real recording goes cut" in v1              # column 3


def test_content_drift_in_a_row_is_visible(tmp_path):
    same = tmp_path / "same.md"
    drifted = tmp_path / "drifted.md"
    same.write_text("| **v1** | verified recorded-source flow | a real recording goes cut |\n")
    drifted.write_text("| **v1** | TOTALLY DIFFERENT SCOPE | nothing at all, ship it blind |\n")
    assert roadmap_rows(same) != roadmap_rows(drifted)


def test_emphasis_and_whitespace_differences_are_not_drift(tmp_path):
    """Normalising these is what keeps the guard from crying wolf — but it must
    normalise ONLY these."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("| **v1** | verified *recorded-source* flow | done |\n")
    b.write_text("|  v1   |    verified recorded-source   flow |   done  |\n")
    assert roadmap_rows(a) == roadmap_rows(b)


def test_non_roadmap_tables_are_not_picked_up(tmp_path):
    """Both documents carry other tables. A row starting `| verification |`
    begins with a 'v' and must not be mistaken for a version row."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "| verification | own it, at every boundary | the one thing no tool does |\n"
        "| **visual orientation** | portrait | correct |\n"
        "| **v1** | verified recorded-source flow | done |\n"
    )
    rows = roadmap_rows(doc)
    assert len(rows) == 1
    assert rows[0].startswith("v1 |")


def test_a_document_with_no_roadmap_table_yields_nothing(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# a document\n\nno tables here at all.\n")
    assert roadmap_rows(empty) == []


def test_the_script_exits_zero_on_the_real_documents():
    """End to end, as CI runs it — the parser being right is not the same fact
    as the script wiring it up right."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_roadmap_sync.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "roadmap in sync" in proc.stdout
