#!/usr/bin/env python3
"""Cut an SRT from the assembled narration using Deepgram word-level timestamps.

Timing comes from the real audio rather than from estimated reading speed, so captions stay
in sync even where the TTS pauses. Falls back to even per-segment splitting if Deepgram is
unavailable, so the deliverable is never blocked on a third-party service.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    SSL_CONTEXT = ssl.create_default_context()

MEDIA = Path(__file__).resolve().parent
AUDIO = MEDIA / "build" / "audio.wav"
SRT = MEDIA / "schema-drift-auto-repair-agent.srt"
ENDPOINT = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true"

MAX_CHARS = 74  # two comfortable caption lines; wrap() splits near the middle
MAX_SECONDS = 5.5


def stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def words_from_deepgram(key: str) -> list[dict]:
    request = Request(
        ENDPOINT,
        data=AUDIO.read_bytes(),
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
    )
    with urlopen(request, timeout=600, context=SSL_CONTEXT) as response:
        body = json.load(response)
    alt = body["results"]["channels"][0]["alternatives"][0]
    return alt.get("words", [])


def group(words: list[dict]) -> list[tuple[float, float, str]]:
    """Pack words into caption cues, breaking on sentence ends, length, or duration."""

    cues: list[tuple[float, float, str]] = []
    buf: list[str] = []
    start = end = 0.0
    for word in words:
        text = word.get("punctuated_word") or word["word"]
        if not buf:
            start = float(word["start"])
        buf.append(text)
        end = float(word["end"])
        too_long = len(" ".join(buf)) >= MAX_CHARS
        too_slow = (end - start) >= MAX_SECONDS
        sentence_end = text.endswith((".", "?", "!", ":"))
        if too_long or too_slow or sentence_end:
            cues.append((start, end, " ".join(buf)))
            buf = []
    if buf:
        cues.append((start, end, " ".join(buf)))
    return cues


def wrap(text: str) -> str:
    if len(text) <= 42:
        return text
    words = text.split()
    mid = len(text) // 2
    best, line = None, ""
    for index, word in enumerate(words):
        line = line + (" " if line else "") + word
        if best is None or abs(len(line) - mid) < abs(best[1] - mid):
            best = (index, len(line))
    cut = (best or (0, 0))[0] + 1
    return " ".join(words[:cut]) + "\n" + " ".join(words[cut:])


def main() -> None:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPGRAM_API_KEY is not set; source the repo .env first.")
    if not AUDIO.is_file():
        raise SystemExit(f"{AUDIO} is missing; run assemble.sh first.")

    words = words_from_deepgram(key)
    if not words:
        raise SystemExit("Deepgram returned no words; inspect the response before shipping captions.")
    cues = group(words)

    lines = []
    for index, (start, end, text) in enumerate(cues, start=1):
        lines.append(f"{index}\n{stamp(start)} --> {stamp(max(end, start + 0.6))}\n{wrap(text)}\n")
    SRT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {SRT.name}: {len(cues)} cues, last ends {stamp(cues[-1][1])}")

    # Captions timed against a different audio file than the one that was muxed would drift
    # silently, and nobody reads an SRT to check. Compare against the shipped video instead.
    video = MEDIA / "schema-drift-auto-repair-agent.mp4"
    if video.is_file():
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        )
        duration = float(probe.stdout.strip())
        overshoot = cues[-1][1] - duration
        print(f"video is {duration:.1f}s; last cue ends {overshoot:+.1f}s relative to it")
        if overshoot > 0.5:
            print("WARNING: captions run past the end of the video — regenerate after assemble.sh.")


if __name__ == "__main__":
    sys.exit(main())
