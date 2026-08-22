import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_roadmap_sync import roadmap_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_readme_and_spec_roadmaps_agree():
    readme = roadmap_rows(ROOT / "README.md")
    spec = roadmap_rows(ROOT / "docs/specs/2026-08-22-cutline-v1-design.md")
    assert readme, "no roadmap rows found in README — the parser or the doc changed shape"
    assert readme == spec, f"roadmap drift:\n README {readme}\n SPEC   {spec}"
