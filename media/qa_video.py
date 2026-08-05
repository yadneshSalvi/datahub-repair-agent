#!/usr/bin/env python3
"""Gate the finished demo against the defects that got v1 rejected.

Checks, in order of how badly v1 failed them:

  1. DURATION      <= 3:00, the Devpost hard limit.
  2. STATIC        no motionless stretch longer than MAX_STATIC seconds. v1 had three
                   (~40s, ~40s, ~30s) because the assembler padded short clips by freezing
                   the last frame. This is the check that would have caught it.
  3. LOADING       no frame containing a skeleton/spinner. Approximated by looking for the
                   flat, low-contrast grey blocks a skeleton produces in an otherwise
                   high-contrast dark UI, and reported as frame timestamps to eyeball.
  4. BLACK         no fully black frames at cut points.

Motion is measured on a downscaled greyscale signal so that a moving cursor and a scrolling
panel both register, without paying for full-resolution decoding.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MEDIA = Path(__file__).resolve().parent
VIDEO = MEDIA / "schema-drift-auto-repair-agent.mp4"

FPS = 4               # sample rate for the motion signal
# 192x108, not something smaller: at 64x36 the 26px cursor shrinks below a pixel and its
# motion vanishes into rounding, so a shot with a moving pointer scored identical to a frozen
# one. That mis-scored the first v2 cut in both directions and is why this is not tuned lower.
WIDTH, HEIGHT = 192, 108
MAX_DURATION = 180.0
MAX_STATIC = 5.0      # seconds
# Mean absolute 8-bit delta below which nothing meaningful moved. Calibrated on the shipped
# cut: pointer-only motion measures ~0.04-0.07, a camera pan or scroll measures >1, and the
# median frame pair is ~2.3. 0.5 sits in the gap, so this flags genuine freezes without
# firing on a slow pan across a mostly-white page.
STATIC_EPS = 0.5


def probe(path: Path, entries: str) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def grey_frames(path: Path) -> list[bytes]:
    """Decode the whole video as a tiny greyscale stream: one bytes object per sample."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    )
    size = WIDTH * HEIGHT
    data = proc.stdout
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


def mean_abs_delta(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def main() -> int:
    if not VIDEO.is_file():
        raise SystemExit(f"{VIDEO} is missing; run assemble.sh first.")

    problems: list[str] = []

    duration = float(probe(VIDEO, "format=duration"))
    dims = probe(VIDEO, "stream=width,height").splitlines()[0]
    print(f"file      {VIDEO.name}")
    print(f"size      {dims.replace(',', 'x')}")
    print(f"duration  {duration:.1f}s ({int(duration // 60)}:{duration % 60:04.1f})")
    if duration > MAX_DURATION:
        problems.append(f"duration {duration:.1f}s exceeds the {MAX_DURATION:.0f}s hard limit")

    frames = grey_frames(VIDEO)
    print(f"sampled   {len(frames)} frames at {FPS}fps")
    if len(frames) < 2:
        raise SystemExit("could not decode enough frames to analyse")

    deltas = [mean_abs_delta(frames[i - 1], frames[i]) for i in range(1, len(frames))]

    # --- static stretches ---
    runs: list[tuple[float, float]] = []
    start = None
    for index, delta in enumerate(deltas):
        if delta < STATIC_EPS:
            if start is None:
                start = index
        else:
            if start is not None:
                runs.append((start / FPS, index / FPS))
                start = None
    if start is not None:
        runs.append((start / FPS, len(deltas) / FPS))

    long_runs = [(a, b) for a, b in runs if b - a > MAX_STATIC]
    worst = max((b - a for a, b in runs), default=0.0)
    print(f"motion    longest static stretch {worst:.1f}s (limit {MAX_STATIC:.0f}s)")
    for a, b in long_runs:
        problems.append(f"static {b - a:.1f}s from {a:.1f}s to {b:.1f}s")

    # --- black frames ---
    black = [i / FPS for i, f in enumerate(frames) if max(f) < 24]
    if black:
        problems.append(f"{len(black)} near-black frame(s), first at {black[0]:.1f}s")
    print(f"black     {len(black)} frame(s)")

    # --- candidate loading frames ---
    # A skeleton is a large area of flat mid-grey. The real UI is near-black with bright
    # accents, so a frame whose pixels cluster tightly in the mid range is suspicious.
    suspects = []
    for index, frame in enumerate(frames):
        mid = sum(1 for p in frame if 40 <= p <= 110)
        if mid / len(frame) > 0.55:
            suspects.append(index / FPS)
    print(f"loading   {len(suspects)} suspicious frame(s)")
    if suspects:
        problems.append(
            f"{len(suspects)} possible loading frame(s), first at {suspects[0]:.1f}s — inspect"
        )

    print()
    if problems:
        print("FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("QA PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
