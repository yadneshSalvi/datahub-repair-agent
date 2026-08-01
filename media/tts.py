#!/usr/bin/env python3
"""Generate the demo narration with Gemini TTS.

Each paragraph of narration.txt becomes one segment, so the video editor can align
scene cuts to sentence boundaries instead of guessing inside a monolithic audio file.
Outputs media/raw/seg_NN.wav plus a manifest with per-segment durations.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import wave
from pathlib import Path
from urllib.request import Request, urlopen

try:  # macOS system Python ships without a usable CA bundle
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - falls back to the platform store
    SSL_CONTEXT = ssl.create_default_context()

MEDIA = Path(__file__).resolve().parent
RAW = MEDIA / "raw"
MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-pro-preview-tts")
VOICE = os.environ.get("TTS_VOICE", "Charon")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Delivery direction. Gemini TTS honours a natural-language style prompt.
STYLE = (
    "Read as a confident, calm technical narrator for a product demo video. "
    "Measured pace, clear consonants, no salesy energy. Slight pause at sentence ends. "
    "Say the text exactly as written:\n\n"
)


def synthesize(text: str, key: str) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
    }
    request = Request(
        ENDPOINT.format(model=MODEL, key=key),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=300, context=SSL_CONTEXT) as response:
        body = json.load(response)
    try:
        part = body["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError) as exc:  # surface the API's own message, not a traceback
        raise SystemExit(f"Unexpected TTS response: {json.dumps(body)[:600]}") from exc
    return base64.b64decode(part["data"])


def write_wav(path: Path, pcm: bytes, rate: int = 24000) -> float:
    """Gemini returns raw signed 16-bit little-endian mono PCM; wrap it in a WAV header."""

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return len(pcm) / (rate * 2)


def main() -> None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set; source the repo .env first.")
    RAW.mkdir(parents=True, exist_ok=True)
    paragraphs = [p.strip() for p in (MEDIA / "narration.txt").read_text().split("\n\n") if p.strip()]

    manifest = []
    total = 0.0
    for index, text in enumerate(paragraphs, start=1):
        out = RAW / f"seg_{index:02d}.wav"
        pcm = synthesize(text, key)
        seconds = write_wav(out, pcm)
        total += seconds
        manifest.append({"index": index, "file": out.name, "seconds": round(seconds, 2), "text": text})
        print(f"  seg {index:02d}  {seconds:6.2f}s  {text[:58]}...", flush=True)

    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nTOTAL NARRATION: {total:.1f}s ({total / 60:.2f} min) across {len(manifest)} segments")
    if total > 170:
        print("WARNING: narration alone exceeds 2:50; trim before assembling (hard limit is 3:00).")


if __name__ == "__main__":
    sys.exit(main())
