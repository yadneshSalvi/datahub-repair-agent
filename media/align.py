#!/usr/bin/env python3
"""Map every word of the written narration onto a real timestamp in the rendered audio.

Two things in this video need the same answer to "when is this word spoken?": the split-screen
panels, which reveal a state exactly as the narration names it, and the captions.

Timing comes from Deepgram, but the TEXT never does. An ASR transcript is a guess — on this
narration it renders "order_placed_at" as "order placed at", "twenty three" as "23" and
"incidents API" as "incident's API". Any of those becoming a caption would put a word on
screen that was never written, and a panel keyed off a mis-recognised word would fire at the
wrong moment. So the script is aligned to the transcript token by token and only the
timestamps are borrowed; unmatched script words are interpolated between their neighbours.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the platform store
    SSL_CONTEXT = ssl.create_default_context()

ENDPOINT = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&punctuate=true"

# Spelt-out numbers the TTS says as words but the ASR writes as digits. Normalising both
# sides means the aligner sees a match instead of a substitution, which keeps the words
# around them anchored to real timestamps rather than interpolated ones.
NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}


@dataclass
class Word:
    """One word of the WRITTEN script, with the time it is actually spoken."""

    paragraph: int  # 1-based, matches seg_NN.wav
    index: int  # position within the paragraph, 0-based
    text: str  # verbatim from narration.txt, punctuation intact
    start: float
    end: float


def normalise(token: str) -> str:
    token = re.sub(r"[^\w']", "", token.lower())
    return NUMBERS.get(token, token)


def transcribe(audio: Path, key: str, cache: Path | None = None) -> list[dict]:
    """Return Deepgram's word list, caching it so a re-assemble costs no API call."""

    if cache and cache.is_file():
        return json.loads(cache.read_text())["words"]
    request = Request(
        ENDPOINT,
        data=audio.read_bytes(),
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
    )
    with urlopen(request, timeout=600, context=SSL_CONTEXT) as response:
        body = json.load(response)
    words = body["results"]["channels"][0]["alternatives"][0].get("words", [])
    if not words:
        raise SystemExit("Deepgram returned no words; inspect the response before shipping.")
    if cache:
        cache.write_text(json.dumps({"words": words}, indent=1))
    return words


def align(paragraphs: list[str], asr: list[dict], total: float) -> list[Word]:
    """Give every script word a timestamp, borrowing ASR times where the two agree."""

    script: list[tuple[int, int, str]] = []
    for p_index, paragraph in enumerate(paragraphs, start=1):
        for w_index, token in enumerate(paragraph.split()):
            script.append((p_index, w_index, token))

    left = [normalise(token) for _, _, token in script]
    right = [normalise(word.get("punctuated_word") or word["word"]) for word in asr]

    start: list[float | None] = [None] * len(script)
    end: list[float | None] = [None] * len(script)
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, _ in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            start[i1 + offset] = float(asr[j1 + offset]["start"])
            end[i1 + offset] = float(asr[j1 + offset]["end"])

    # Anything the ASR heard differently sits between two words it heard correctly; spread
    # those evenly across the gap rather than dropping them, so a caption never loses a word.
    known = [i for i, value in enumerate(start) if value is not None]
    if not known:
        raise SystemExit("alignment failed: no script word matched the transcript")
    for position in range(len(script)):
        if start[position] is not None:
            continue
        before = max((i for i in known if i < position), default=None)
        after = min((i for i in known if i > position), default=None)
        low = end[before] if before is not None else 0.0
        high = start[after] if after is not None else total
        span = max(high - low, 0.05)
        if before is None:
            share = span / (after + 1 if after is not None else 1)
            start[position] = max(0.0, high - share * (after - position + 1))
        elif after is None:
            share = span / (len(script) - before)
            start[position] = low + share * (position - before - 1)
        else:
            share = span / (after - before)
            start[position] = low + share * (position - before)
        end[position] = min(start[position] + share, high)

    return [
        Word(paragraph=p, index=w, text=token, start=float(start[i]), end=float(end[i]))
        for i, (p, w, token) in enumerate(script)
    ]


def read_paragraphs(narration: Path) -> list[str]:
    return [block.strip() for block in narration.read_text().split("\n\n") if block.strip()]


def api_key() -> str:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPGRAM_API_KEY is not set; source the repo .env first.")
    return key


def find(words: list[Word], paragraph: int, phrase: str) -> float:
    """Start time of `phrase` inside a paragraph, matched on normalised script words."""

    target = [normalise(token) for token in phrase.split()]
    pool = [word for word in words if word.paragraph == paragraph]
    tokens = [normalise(word.text) for word in pool]
    for index in range(len(tokens) - len(target) + 1):
        if tokens[index : index + len(target)] == target:
            return pool[index].start
    raise SystemExit(f"anchor {phrase!r} not found in narration paragraph {paragraph}")
