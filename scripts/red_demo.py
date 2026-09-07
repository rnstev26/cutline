#!/usr/bin/env python3
"""Acceptance clause 5: a demonstrated RED at each boundary.

Substitutes a deliberately damaged artifact at each boundary and asserts the
boundary check REJECTS it. A green cutline run proves the pipeline can pass;
this proves it can fail, which is the half that is easy to leave unproven.

EVERY case is two-phase, and the order matters:

  1. CONFIRM THE DAMAGE LANDED -- probe the damaged file and assert the property
     actually differs from the source.
  2. Only then assert the boundary rejects it.

Without phase 1 a case that silently failed to damage anything reports
"not rejected" and reads as a guard defect. A check that cannot tell "the guard
failed" from "the damage never happened" is the exact defect class this project
keeps finding -- eight instances by the v1 TURNOVER's own count. Phase 1 is the
positive control.

Usage:
    uv run python scripts/red_demo.py <a-real-mp4>

Exit 0 = every boundary rejected every damaged artifact.

Ran 9/9 on v1's acceptance source, 2026-09-07. The rotation case is skipped
when the source carries none -- that recording did, so rotation, the founding
failure of this project, is still exercised only by synthetic fixtures.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from cutline.flow import BLACK_FRAME_RATIO_THRESHOLD, black_pixel_ratio
from cutline.probe import probe
from cutline.verify import COMPOSITE_POLICY, CUT_POLICY, verify


def ffmpeg(args: list[str], out: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", *args, str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return out


def get(info, prop: str):
    """Read a dotted property off MediaInfo the way the policies name them."""
    if "." not in prop:
        return getattr(info, prop, None)
    head, tail = prop.split(".", 1)
    obj = getattr(info, head, None)
    return getattr(obj, tail, None) if obj is not None else None


def case(name: str, prop: str, src: Path, damaged: Path, policy) -> tuple[bool, str]:
    before, after = probe(src), probe(damaged)

    # Phase 1 -- positive control: did the damage actually land?
    b, a = get(before, prop), get(after, prop)
    if b == a:
        return False, (f"DAMAGE DID NOT LAND: {prop} is {b!r} in both files. "
                       f"This case proves nothing -- fix the case, not the guard.")

    # Phase 2 -- does the boundary refuse it?
    report = verify(before, after, policy)
    if report.ok:
        return False, (f"BOUNDARY ACCEPTED IT: {prop} {b!r} -> {a!r} and "
                       f"[{report.boundary}] reported OK.")
    violated = {c.prop for c in report.changes} if hasattr(
        next(iter(report.changes)), "prop") else set()
    detail = f"{prop} {b!r} -> {a!r}; rejected by [{report.boundary}]"
    if violated and prop not in violated:
        detail += f" -- but on {sorted(violated)}, NOT on {prop}"
        return False, "REJECTED FOR THE WRONG REASON: " + detail
    return True, detail


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]).resolve()
    if not src.is_file():
        sys.exit(f"no such file: {src}")

    info = probe(src)
    print(f"source: {src.name}  {info.video.width}x{info.video.height} "
          f"{info.video.codec} / {info.audio.codec} "
          f"{info.audio.sample_rate}Hz {info.audio.channels}ch\n")

    tmp = Path(tempfile.mkdtemp(prefix="cutline-red-"))
    results: list[tuple[str, bool, str]] = []

    # --- CUT boundary: every invariant the cut is supposed to hold ---------
    w, h = info.video.width, info.video.height
    cut_cases = [
        ("geometry shrunk", "video.width",
         ["-i", str(src), "-vf", f"scale={w // 2}:{h // 2}", "-c:a", "copy"]),
        ("codec swapped to h265", "video.codec",
         ["-i", str(src), "-c:v", "libx265", "-tag:v", "hvc1", "-c:a", "copy"]),
        ("profile forced to baseline", "video.profile",
         ["-i", str(src), "-c:v", "libx264", "-profile:v", "baseline",
          "-pix_fmt", "yuv420p", "-c:a", "copy"]),
        ("audio resampled to 22050", "audio.sample_rate",
         ["-i", str(src), "-c:v", "copy", "-ar", "22050"]),
        ("audio downmixed to mono" if info.audio.channels != 1
         else "audio upmixed to stereo", "audio.channels",
         ["-i", str(src), "-c:v", "copy",
          "-ac", "1" if info.audio.channels != 1 else "2"]),
        ("audio stream dropped", "audio_streams",
         ["-i", str(src), "-c:v", "copy", "-an"]),
    ]
    # Rotation is THE founding failure case -- a 1920x1080 source carrying
    # rotation=90 emerges 1080x1920 with the side data gone while duration,
    # frame count, stream count and codec all stay identical. Only testable on
    # a source that actually carries rotation, which a phone recording does and
    # a synthetic fixture does not.
    if info.rotation:
        cut_cases.insert(0, ("rotation side-data stripped", "rotation",
                             ["-i", str(src), "-c", "copy",
                              "-metadata:s:v:0", "rotate=0"]))
    else:
        print("  --  rotation: source carries none; case not applicable "
              "(a phone recording WILL exercise it)")

    print("CUT boundary")
    for label, prop, args in cut_cases:
        out = tmp / f"cut_{prop.replace('.', '_')}.mp4"
        try:
            ffmpeg(args, out)
        except RuntimeError as e:
            results.append((f"cut/{label}", False, f"could not build case: {e}"))
            print(f"  ??  {label}: could not build case")
            continue
        ok, detail = case(label, prop, src, out, CUT_POLICY)
        results.append((f"cut/{label}", ok, detail))
        print(f"  {'RED' if ok else '!! '} {label}: {detail}")

    # --- COMPOSITE boundary -----------------------------------------------
    # Its only hard invariant is video.codec; a black render is refused by a
    # separate guard in flow.caption(), so it is exercised separately below.
    print("\nCOMPOSITE boundary")
    out = tmp / "composite_codec.mp4"
    ffmpeg(["-i", str(src), "-c:v", "libx265", "-tag:v", "hvc1", "-c:a", "copy"], out)
    ok, detail = case("codec swapped to h265", "video.codec", src, out,
                      COMPOSITE_POLICY)
    results.append(("composite/codec swapped", ok, detail))
    print(f"  {'RED' if ok else '!! '} codec swapped to h265: {detail}")

    # Black-frame guard: not a policy property, a separate refusal in caption().
    black = tmp / "composite_black.mp4"
    dur = min(float(info.duration or 5), 5.0)
    ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={dur}",
            "-i", str(src), "-map", "0:v", "-map", "1:a", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy"], black)
    ratio = black_pixel_ratio(black)
    ok = ratio >= BLACK_FRAME_RATIO_THRESHOLD
    detail = (f"black_pixel_ratio {ratio:.1%} vs threshold "
              f"{BLACK_FRAME_RATIO_THRESHOLD:.0%}")
    results.append(("composite/black render", ok, detail))
    print(f"  {'RED' if ok else '!! '} all-black render: {detail}")

    # Negative control: the guard must NOT fire on the healthy source.
    healthy = black_pixel_ratio(src)
    ok = healthy < BLACK_FRAME_RATIO_THRESHOLD
    detail = (f"black_pixel_ratio {healthy:.1%} on the UNDAMAGED source "
              f"-- must stay under {BLACK_FRAME_RATIO_THRESHOLD:.0%}")
    results.append(("control/healthy source not flagged", ok, detail))
    print(f"  {'ok ' if ok else '!! '} negative control: {detail}")

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} boundaries behaved correctly")
    print(f"artifacts: {tmp}")
    if failed:
        print("\nFAILED:")
        for n, d in failed:
            print(f"  {n}: {d}")
        sys.exit(1)
    print("\nAcceptance clause 5 satisfied: every boundary rejected its damaged "
          "artifact, and the black-frame guard stayed quiet on a healthy one.")


if __name__ == "__main__":
    main()
