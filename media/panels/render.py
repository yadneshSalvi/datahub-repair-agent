#!/usr/bin/env python3
"""Render every panel state and feature chip to PNG with headless Chrome.

Panels are rendered at 2x (1520x2160) because `assemble.sh` composites on a 2x master and
only downsamples at the very end — so the panel text is supersampled exactly like the
browser-captured footage beside it, instead of being upscaled from 1x.

States are still frames, not a video. The reveal animation is built in `assemble.sh` by
holding each state and cross-dissolving to the next at a word timestamp, which makes the
sync exact and the render deterministic — a recorded CSS animation would have to be
re-timed by hand every time a narration word moves.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "png"
SOURCE = HERE / "panels.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# panel id -> number of reveal states
PANELS = {"A": 8, "B": 6, "C": 6}
CHIPS = {"schema": (900, 200), "lineage": (900, 200), "validate": (900, 200),
         "speed": (760, 260)}


def shot(url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    flags = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=2",
        f"--window-size={width},{height}",
        f"--screenshot={out}",
        "--virtual-time-budget=3000",
    ]
    if transparent:
        flags.append("--default-background-color=00000000")
    flags.append(url)
    result = subprocess.run(flags, capture_output=True, text=True)
    if not out.is_file():
        raise SystemExit(f"chrome produced no PNG for {url}\n{result.stderr[-800:]}")


def main() -> int:
    if not Path(CHROME).is_file():
        raise SystemExit(f"Chrome not found at {CHROME}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    base = SOURCE.as_uri()
    for panel, states in PANELS.items():
        for state in range(1, states + 1):
            out = OUT / f"panel{panel}_{state:02d}.png"
            shot(f"{base}?panel={panel}&state={state}", out, 760, 1080, False)
            print(f"  panel {panel} state {state} -> {out.name}")

    # Chips render into an oversized transparent window with the box pinned at the top-left,
    # so overlaying the whole PNG at (x, y) puts the chip's corner exactly at (x, y) and the
    # surrounding transparency costs nothing.
    for chip, (width, height) in CHIPS.items():
        out = OUT / f"chip_{chip}.png"
        shot(f"{base}?chip={chip}", out, width, height, True)
        print(f"  chip {chip} -> {out.name}")

    print(f"\n{len(list(OUT.glob('*.png')))} PNGs in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
