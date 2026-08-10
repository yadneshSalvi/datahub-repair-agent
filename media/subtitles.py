#!/usr/bin/env python3
"""Cut the SRT from the written narration, timed by Deepgram word alignment.

Two rules, both learned the hard way on earlier cuts:

1. **The words come from the script, never from the transcript.** ASR is a guess; on this
   narration it writes "incidents API" as "incident's API" and "twenty three" as "23". A
   recognition error that reaches the screen is a caption of something nobody said.
2. **No orphan cues.** A previous cut shipped a one-word caption because a sentence ended
   just after a break; a trailing fragment is now merged back into the cue before it rather
   than fixed by hand afterwards.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align

MEDIA = Path(__file__).resolve().parent
AUDIO = MEDIA / "build" / "audio.wav"
VIDEO = MEDIA / "schema-drift-auto-repair-agent.mp4"
SRT = MEDIA / "schema-drift-auto-repair-agent.srt"

MAX_CHARS = 74  # two comfortable caption lines; wrap() splits near the middle
MAX_SECONDS = 5.5
MIN_WORDS = 3  # anything shorter is a fragment, not a cue

# narration.txt is spelt for the EAR — "M C P", "order placed at", "SQL Glot" — because that
# is what makes the TTS say them correctly. A reader wants the written form. These collapse
# a run of script words into the thing a developer would actually type, keeping the first
# word's start time and the last word's end time, which also stops a cue ever breaking in
# the middle of an identifier.
PHRASES: list[tuple[list[str], str]] = [
    (["M", "C", "P"], "MCP"),
    (["A", "P", "I"], "API"),
    (["order", "I", "D"], "order ID"),
    (["SQL", "Glot"], "sqlglot"),
    (["order", "placed", "at"], "order_placed_at"),
    (["order", "created", "at"], "order_created_at"),
    (["order", "date"], "order_date"),
    (["column", "level", "lineage"], "column-level lineage"),
    (["fine", "grained", "lineage"], "fine-grained lineage"),
    (["catalog", "write", "back"], "catalog write-back"),
    (["Twenty", "three"], "23"),
    (["twenty", "three"], "23"),
]

# Spelt-out figures that are read as prose but belong on screen as numerals, scoped to the
# one paragraph that recites the validation breakdown so "Three answers, not two" elsewhere
# keeps reading as English.
FIGURES: dict[int, dict[str, str]] = {10: {"fifteen": "15", "six": "6", "two": "2"}}

# A cue that ends on one of these reads as a sentence cut in half; it moves to the next cue.
DANGLING = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "with", "that", "its", "it"}


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def key(text: str) -> str:
    """Strip punctuation only.

    Deliberately NOT `align.normalise`, which also folds spelt-out numbers to digits for the
    aligner's benefit — that would turn "Twenty three" into "20 3" and the phrase table
    below would silently never match.
    """

    return re.sub(r"[^\w']", "", text.lower())


def render(words: list[align.Word]) -> list[align.Word]:
    """Rewrite the script's ear-spellings into the forms a reader expects."""

    out: list[align.Word] = []
    index = 0
    while index < len(words):
        for tokens, replacement in PHRASES:
            window = words[index : index + len(tokens)]
            if len(window) != len(tokens):
                continue
            if [key(word.text) for word in window] != [token.lower() for token in tokens]:
                continue
            if len({word.paragraph for word in window}) != 1:
                continue
            tail = window[-1].text
            trailing = tail[len(tail.rstrip(".,:;!?")) :]
            out.append(align.Word(window[0].paragraph, window[0].index,
                                  replacement + trailing, window[0].start, window[-1].end))
            index += len(tokens)
            break
        else:
            word = words[index]
            figure = FIGURES.get(word.paragraph, {}).get(key(word.text))
            if figure:
                tail = word.text
                word = align.Word(word.paragraph, word.index,
                                  figure + tail[len(tail.rstrip(".,:;!?")) :], word.start, word.end)
            out.append(word)
            index += 1
    return out


def group(words: list[align.Word]) -> list[tuple[float, float, str]]:
    cues: list[list[align.Word]] = []
    buf: list[align.Word] = []
    for word in words:
        # A caption may not straddle a shot change: the picture cuts, so the words under it
        # must cut too.
        if buf and word.paragraph != buf[-1].paragraph:
            cues.append(buf)
            buf = []
        buf.append(word)
        text = " ".join(item.text for item in buf)
        span = buf[-1].end - buf[0].start
        if len(text) >= MAX_CHARS or span >= MAX_SECONDS or word.text.endswith((".", "?", "!", ":")):
            cues.append(buf)
            buf = []
    if buf:
        cues.append(buf)

    # Push a trailing function word onto the next cue rather than ending a caption on it.
    for index in range(len(cues) - 1):
        while (
            len(cues[index]) > 1
            and cues[index][-1].text.lower() in DANGLING
            and cues[index][-1].paragraph == cues[index + 1][0].paragraph
        ):
            cues[index + 1].insert(0, cues[index].pop())

    merged: list[list[align.Word]] = []
    for cue in cues:
        if not cue:
            continue
        if (
            merged
            and len(cue) < MIN_WORDS
            and merged[-1][-1].paragraph == cue[0].paragraph
            and len(" ".join(item.text for item in merged[-1] + cue)) <= MAX_CHARS + 16
        ):
            merged[-1].extend(cue)
        else:
            merged.append(cue)

    return [(cue[0].start, cue[-1].end, " ".join(item.text for item in cue)) for cue in merged]


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


def main() -> int:
    if not AUDIO.is_file():
        raise SystemExit(f"{AUDIO} is missing; run assemble.py first.")

    paragraphs = align.read_paragraphs(MEDIA / "narration.txt")
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(AUDIO)],
        capture_output=True, text=True, check=True,
    )
    total = float(duration.stdout.strip())
    words = align.align(
        paragraphs,
        align.transcribe(AUDIO, align.api_key(), MEDIA / "build" / "words_final.json"),
        total,
    )
    cues = group(render(words))

    lines = []
    for index, (start, end, text) in enumerate(cues, start=1):
        lines.append(f"{index}\n{stamp(start)} --> {stamp(max(end, start + 0.6))}\n{wrap(text)}\n")
    SRT.write_text("\n".join(lines), encoding="utf-8")

    shortest = min(len(text.split()) for _, _, text in cues)
    print(f"wrote {SRT.name}: {len(cues)} cues, shortest {shortest} words, "
          f"last ends {stamp(cues[-1][1])}")

    # Captions timed against a different audio file than the one that was muxed would drift
    # silently, and nobody reads an SRT to check. Compare against the shipped video instead.
    if VIDEO.is_file():
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(VIDEO)],
            capture_output=True, text=True, check=True,
        )
        video = float(probe.stdout.strip())
        overshoot = cues[-1][1] - video
        print(f"video is {video:.1f}s; last cue ends {overshoot:+.1f}s relative to it")
        if overshoot > 0.5:
            raise SystemExit("captions run past the end of the video — regenerate after assemble.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
