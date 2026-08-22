#!/usr/bin/env python3
"""Fail when the README and spec roadmap tables disagree.

Both documents carry the same version/adds/done-when table. Manual syncing
drifted three times during authoring; this makes the drift loud.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROW = re.compile(r"^\|\s*\*{0,2}(v[0-9.]+)\*{0,2}\s*\|")


def roadmap_rows(path: Path) -> list[str]:
    """Version labels, in order, from the roadmap table in `path`."""
    return [m.group(1) for line in path.read_text().splitlines() if (m := ROW.match(line))]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    readme = roadmap_rows(root / "README.md")
    spec = roadmap_rows(root / "docs/specs/2026-08-22-cutline-v1-design.md")
    if not readme:
        print("no roadmap rows found in README.md", file=sys.stderr)
        return 1
    if readme != spec:
        print(f"roadmap drift:\n  README {readme}\n  SPEC   {spec}", file=sys.stderr)
        return 1
    print(f"roadmap in sync: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
