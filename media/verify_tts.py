#!/usr/bin/env python3
"""Transcribe every narration segment and diff it against the script.

v1 shipped with mispronunciations baked into both the audio and the subtitles
("order play stat" for order_placed_at, "SQLOT" for sqlglot, "Anything" for "Anyone").
Nothing caught them because nobody listened. This closes that hole: each generated wav
is sent back through Deepgram and compared word-for-word with the text it was generated
from, so a mangled word fails the build instead of reaching the judges.

Exit code is non-zero if any segment diverges beyond the allowed normalisations.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import ssl
import sys
import wave
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    SSL_CONTEXT = ssl.create_default_context()

MEDIA = Path(__file__).resolve().parent
RAW = MEDIA / "raw"
ENDPOINT = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true"

# Deepgram writes back conventional orthography where the script spells things out for the
# synthesiser. These are transcription-side spellings, NOT pronunciation errors, so they are
# folded away before diffing. Anything not listed here is a real divergence worth reading.
EQUIVALENTS = {
    "mcp": "m c p",
    "id": "i d",
    "sqlglot": "sql glot",
    "sql-glot": "sql glot",
    "datahub": "data hub",
    "23": "twenty three",
    "opensource": "open source",
    # Deepgram americanises this; same word, same sound, not a mispronunciation.
    "gray": "grey",
}


def normalise(text: str) -> list[str]:
    lowered = text.lower().replace("—", " ").replace("-", " ")
    for src, dst in EQUIVALENTS.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered)
    return re.findall(r"[a-z0-9']+", lowered)


def transcribe(path: Path, key: str) -> str:
    request = Request(
        ENDPOINT,
        data=path.read_bytes(),
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
    )
    with urlopen(request, timeout=600, context=SSL_CONTEXT) as response:
        body = json.load(response)
    return body["results"]["channels"][0]["alternatives"][0]["transcript"]


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main() -> int:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPGRAM_API_KEY is not set; source the repo .env first.")

    paragraphs = [p.strip() for p in (MEDIA / "narration.txt").read_text().split("\n\n") if p.strip()]
    failures = 0
    total = 0.0

    for index, script in enumerate(paragraphs, start=1):
        wav = RAW / f"seg_{index:02d}.wav"
        if not wav.is_file():
            print(f"seg {index:02d}  MISSING {wav.name}")
            failures += 1
            continue
        total += duration(wav)
        heard = transcribe(wav, key)
        want, got = normalise(script), normalise(heard)
        if want == got:
            print(f"seg {index:02d}  OK    {duration(wav):5.2f}s  {len(want):3d} words")
            continue

        failures += 1
        print(f"\nseg {index:02d}  DIVERGED  {duration(wav):5.2f}s")
        for line in difflib.unified_diff(want, got, "script", "heard", lineterm="", n=2):
            if line.startswith(("---", "+++", "@@")):
                continue
            print(f"      {line}")
        print(f"      heard: {heard}\n")

    print(f"\nTOTAL {total:.1f}s ({total / 60:.2f} min) across {len(paragraphs)} segments")
    if total > 180:
        print(f"WARNING: {total:.1f}s exceeds the 3:00 hard limit before any tempo fit.")
    print("VERIFICATION PASSED" if failures == 0 else f"VERIFICATION FAILED: {failures} segment(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
