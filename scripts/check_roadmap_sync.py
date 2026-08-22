#!/usr/bin/env python3
"""Fail when the README and spec roadmap tables disagree.

Both documents carry the same version/adds/done-when table. Manual syncing
drifted three times during authoring; this makes the drift loud.

It compares the WHOLE ROW, not just the version label. It used to extract only
`(v[0-9.]+)` from column 1 and compare that list, while its docstring and the CI
step's name claimed it kept the table in sync. Measured in review: rewriting the
README's v1 row — "adds" to `TOTALLY DIFFERENT SCOPE`, "done when" to `nothing
at all, ship it blind` — left this script printing `roadmap in sync` and exiting
0. A guard keyed on a column that cannot drift is not a guard.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SPEC = "docs/specs/2026-08-22-cutline-v1-design.md"

# Row selection is unchanged: a roadmap row is one whose first cell is a version
# label. Both documents contain OTHER tables with rows starting "| verification"
# and "| **visual orientation**", and those are not roadmap rows.
ROW = re.compile(r"^\|\s*\*{0,2}v[0-9.]+\*{0,2}\s*\|")

# What legitimately differs between two hand-maintained copies of one table:
# emphasis markers and whitespace. Everything else is content, and content
# differing IS the drift this exists to catch — so nothing else is normalised.
# Backticks in particular are left alone: `v3` and v3 are a real difference.
_EMPHASIS = re.compile(r"[*_]")
_SPACES = re.compile(r"\s+")


def _normalise(line: str) -> str:
    cells = line.strip().strip("|").split("|")
    return " | ".join(_SPACES.sub(" ", _EMPHASIS.sub("", c)).strip() for c in cells)


def roadmap_rows(path: Path) -> list[str]:
    """Whole roadmap rows, in order, normalised for emphasis and whitespace."""
    return [_normalise(line) for line in path.read_text().splitlines() if ROW.match(line)]


def _label(row: str) -> str:
    return row.split(" | ", 1)[0]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    readme = roadmap_rows(root / "README.md")
    spec = roadmap_rows(root / SPEC)
    if not readme:
        print("no roadmap rows found in README.md", file=sys.stderr)
        return 1
    if not spec:
        print(f"no roadmap rows found in {SPEC}", file=sys.stderr)
        return 1
    if readme != spec:
        print("roadmap drift between README.md and the spec:", file=sys.stderr)
        for a, b in zip(readme, spec, strict=False):
            if a != b:
                print(f"  {_label(a)}\n    README {a}\n    SPEC   {b}", file=sys.stderr)
        if len(readme) != len(spec):
            print(
                f"  row COUNT differs: README {len(readme)}, SPEC {len(spec)}\n"
                f"    README {[_label(r) for r in readme]}\n"
                f"    SPEC   {[_label(r) for r in spec]}",
                file=sys.stderr,
            )
        return 1
    print(f"roadmap in sync: {len(readme)} rows, {[_label(r) for r in readme]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
