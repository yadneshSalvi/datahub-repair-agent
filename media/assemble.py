#!/usr/bin/env python3
"""Assemble the demo video: camera treatment, split-screen panels, narration, mux.

This replaces the shell assembler. The camera grammar it implements is unchanged and still
the one that was accepted on review; what it adds is the split-screen technical panels, and
those need word-level audio timing to decide when each panel state appears — which is a
poor fit for bash and an easy one for Python.

CAMERA GRAMMAR (unchanged). Per full-frame shot:

  1. ESTABLISH   full frame, pixel-locked, 1.8s
  2. HIGHLIGHT   a violet rectangle around the region about to be discussed, 0.8s BEFORE
                 the move, so the eye finds it first
  3. ZOOM        1.0s, ease-in-out cubic, full frame -> target crop
  4. HOLD        that crop, perfectly static, for the rest of the shot

At most one camera move per shot; every cut happens at full frame. Long static holds are
correct — the UI's own motion carries the shot. No pans, no drift, no Ken Burns.

SPLIT-SCREEN. A panel shot replaces step 3 with a single 1.0s dissolve into a two-up
composition: the technical panel on the left, a fixed crop of real master pixels on the
right. The camera does not move at any point in a panel shot; only the panel's own content
animates, and it animates on the word that introduces it. A panel can span two consecutive
shots (`hold` mode), so the panel stays put while the footage beside it cuts — one entry,
one exit, instead of two of each.

Things worth knowing before changing anything:

* v1 stretched a short clip to its narration length by FREEZING the last frame, which
  produced 30-40 second motionless stretches. A clip shorter than its segment is a hard
  error here, never something to pad.
* Playwright's video pipeline ignores CSS zoom, so close-ups are made HERE, out of real
  pixels, never by zooming the browser.
* Every move is computed on a 2x master (3840x2160) and rounded only at output, so it is
  sub-pixel smooth rather than stepping. Panels are rendered at 2x for the same reason.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align

MEDIA = Path(__file__).resolve().parent
RAW = MEDIA / "raw"
BUILD = MEDIA / "build"
PANELS = MEDIA / "panels" / "png"
OUTPUT = MEDIA / "schema-drift-auto-repair-agent.mp4"

W, H = 1920, 1080
PANEL_W = 760  # 1x; the footage pane takes the remaining 1160
PANE_W = W - PANEL_W
HL_COLOR = "0x9184ff"  # the brand violet, on the dark UI and on DataHub's white pages
EST = 1.8  # full-frame establish before anything moves
LEAD = 0.8  # highlight appears this long before the move starts
MOVE = 1.0  # zoom, or split-screen dissolve
SPLIT_AT = EST + LEAD - MOVE / 2  # dissolve starts here, lands at EST + LEAD + MOVE/2
STATE_FADE = 0.25  # cross-dissolve between two panel states
CHIP_FADE = 0.3
CHIP_HOLD = 5.0
BORDER_LEAD = 0.8  # a border lands on its target this long before the word that names it
TARGET = float(__import__("os").environ.get("TARGET", 174))


@dataclass
class Shot:
    n: str
    trim: float
    speed: float
    highlight: str | None = None  # x:y:w:h on the 1920x1080 master
    crop: str | None = None  # x:y:w:h; the close-up, or the split-screen pane
    panel: str | None = None  # A / B / C
    panel_mode: str = "enter"  # enter = dissolve in; hold = already split at frame 0
    chip: str | None = None
    chip_at: tuple[int, str] | float | None = None  # (paragraph, phrase), or seconds in
    chip_hold: float | None = None  # None = CHIP_HOLD; otherwise how long it stays
    chip_xy: tuple[int, int] = (60, 946)
    # A shot may replace its own footage in the pane with a still of a persisted run, with
    # violet borders stepping between the things the narration names.
    still: str | None = None
    still_crop: str | None = None  # x:y:w:h on the 1920x1080 still
    borders: list[tuple[str, tuple[int, int, int, int]]] = field(default_factory=list)
    want: float = 0.0  # narration length, filled in from the audio

    @property
    def n_paragraph(self) -> int:
        """Shots are 1:1 with narration paragraphs, so the index is the shot number."""
        return int(self.n)
    start: float = 0.0  # start time in the assembled narration
    panel_offset: float = 0.0  # where this shot begins inside its panel's own timeline
    panel_len: float = 0.0


# Every rectangle below was measured off the actual master frame for that shot, so a
# highlight lands on a real UI region rather than floating over nothing. Shots 01 and 13
# share a crop on purpose: the close is a match cut on the open. For a panel shot the
# highlight IS the pane crop — it marks the region that is about to become the right half.
SHOTS: list[Shot] = [
    Shot("01", 6, 1, "68:296:1240:360", "40:95:1360:765"),
    Shot("02", 6, 1, "120:100:892:830", "120:100:892:830", panel="A"),
    # Highlight is the Rename card ONLY. A wider box spilled into the neighbouring Retype
    # card, which is not what the line is about.
    Shot("03", 3, 1, "268:196:545:200", "136:40:1000:562"),
    # This shot used to stay full frame because the two schema panels span the master. They
    # still do — the crop keeps both of them whole and only trims the page header, which
    # carried the run id of an EARLIER run (these first shots predate the filmed run). One
    # run id on camera, and the diff rows get 1.18x while we are here.
    Shot("04", 3, 1, "275:428:1615:56", "262:55:1623:913", chip="schema",
         chip_at=(4, "schema metadata."), chip_xy=(110, 880)),
    # The live timeline auto-scrolled between two positions on a ~12 second cycle, which at
    # 3.4x read as the picture churning up and down — the one thing the user rejected in this
    # cut. Measured before changing anything: the master never holds still for more than 3.5s,
    # so there was no settled window to re-frame and the pane had to be re-shot.
    #
    # It is re-shot WITHOUT re-running the agent: `?run=<id>` opens the persisted run
    # read-only, so the pane is a still of the real UI rendering the real recorded event log,
    # held perfectly locked, with borders stepping between the calls as they are named. The
    # establish still comes from the master at 1x and still contains the genuine click, so
    # nothing in this shot is time-compressed any more and the speed disclosure is gone.
    Shot("05", 6, 1, "1319:490:601:560", "1319:490:601:560", panel="B",
         chip="replay", chip_at=2.6, chip_hold=17.0, chip_xy=(790, 900),
         still="replay05.png", still_crop="1311:225:609:567",
         borders=[
             ("Search, to find", (1291, 232, 286, 69)),
             ("List schema fields,", (1291, 304, 532, 69)),
             ("Get lineage, for", (1291, 377, 532, 69)),
             ("Then get lineage paths", (1291, 522, 503, 69)),
         ]),
    # The panel stays on screen across this cut, so shot 06 opens already split — no second
    # entrance for something that never left.
    Shot("06", 3, 1, None, "175:75:1010:940", panel="B", panel_mode="hold"),
    Shot("07", 3, 1, "268:172:1288:360", "180:0:1460:821", chip="lineage",
         chip_at=(7, "Three answers,"), chip_xy=(980, 40)),
    Shot("08", 5, 1, "1540:56:368:572", "920:60:1000:563"),
    Shot("09", 3, 1, "556:160:908:320", "460:0:1100:619"),
    # No chip here: this beat re-uses schema metadata, already named on shot 04, and every
    # free corner of the validation table is a row the narration is reading out.
    Shot("10", 3, 1, "275:550:1350:450", "200:236:1500:844"),
    Shot("11", 3, 1),
    Shot("12", 3, 1, "255:160:700:652", "255:160:700:652", panel="C"),
    Shot("13", 8, 1, "68:296:1240:360", "40:95:1360:765"),
]

# Which narration word each panel state waits for. State 1 is always the shot's own start.
# These are script words, not transcript words, so a recognition error cannot move a panel.
PANEL_STATES: dict[str, list[tuple[int, str] | None]] = {
    "A": [
        None,
        (2, "Our agent"),
        (2, "through M C P"),
        (2, "Four capabilities"),
        (2, "schema metadata,"),
        (2, "column level lineage,"),
        (2, "incidents,"),
        (2, "and catalog write back."),
    ],
    "B": [
        None,
        (5, "Search, to find"),
        (5, "List schema fields,"),
        (5, "Get lineage, for"),
        (5, "Then get lineage paths"),
        (6, "column level lineage."),
    ],
    "C": [
        None,
        (12, "Corrected fine grained lineage."),
        (12, "The repaired column documented."),
        (12, "Tags on every"),
        (12, "An incident raised"),
        (12, "And the run itself"),
    ],
}


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{' '.join(args)}\n\n{result.stderr[-2500:]}")


def probe(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def scale2(rect: str) -> tuple[int, int, int, int]:
    x, y, w, h = (int(value) for value in rect.split(":"))
    return x * 2, y * 2, w * 2, h * 2


def build_audio() -> float:
    """Concatenate the narration segments and fit the result to TARGET seconds."""

    BUILD.mkdir(exist_ok=True)
    listing = BUILD / "audio_list.txt"
    listing.write_text("".join(f"file '../raw/seg_{shot.n}.wav'\n" for shot in SHOTS))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:a", "pcm_s16le", str(BUILD / "audio_raw.wav")])

    raw = probe(BUILD / "audio_raw.wav")
    # The script is written to be as informative as 3:00 allows, so it lands slightly long.
    # A small speed-up is far less damaging than cutting explanation a first-time viewer
    # needs. Clamped, because past ~1.15 the voice starts to sound harried.
    tempo = min(1.15, max(1.0, raw / TARGET))
    print(f"== tempo fit: {raw:.2f}s -> target {TARGET:.0f}s (atempo {tempo:.4f}) ==")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(BUILD / "audio_raw.wav"),
         "-filter:a", f"atempo={tempo:.6f}", str(BUILD / "audio.wav")])
    return tempo


def panel_video(panel: str, states: list[float], length: float, out: Path) -> None:
    """Render one panel's whole animation: still states cross-dissolving on cue.

    The states are cumulative supersets of one another, so fading state N+1 in on top of
    state N is exactly a cross-dissolve of the newly revealed lines and a no-op everywhere
    else — no reflow, and the reader never has to re-find a line that moved.
    """

    images = sorted(PANELS.glob(f"panel{panel}_*.png"))
    if len(images) != len(states):
        raise SystemExit(f"panel {panel}: {len(images)} PNGs but {len(states)} state times")

    args = ["ffmpeg", "-y", "-v", "error"]
    for image in images:
        args += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(image)]

    chain = ["[0:v]fps=30,format=rgba,setsar=1[base]"]
    current = "base"
    for index, at in enumerate(states[1:], start=1):
        chain.append(
            f"[{index}:v]fps=30,format=rgba,setsar=1,"
            f"fade=t=in:st={at:.3f}:d={STATE_FADE}:alpha=1[s{index}]"
        )
        chain.append(f"[{current}][s{index}]overlay=0:0:format=auto[o{index}]")
        current = f"o{index}"
    chain.append(f"[{current}]format=yuv420p[out]")

    args += ["-filter_complex", ";".join(chain), "-map", "[out]",
             "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
             "-pix_fmt", "yuv420p", str(out)]
    run(args)


def shot_filters(shot: Shot) -> tuple[list[str], list[str], str]:
    """Return (extra inputs, filter chain, label of the finished 1920x1080 stream)."""

    inputs: list[str] = []
    chain: list[str] = []

    pre = f"setpts=PTS/{shot.speed}," if shot.speed != 1 else ""
    chain.append(f"[0:v]{pre}fps=30,scale={W * 2}:{H * 2}:flags=bicubic,setsar=1[m]")

    if shot.panel:
        cx, cy, cw, ch = scale2(shot.crop)
        inputs += ["-i", str(BUILD / f"panel_{shot.panel}_{shot.n}.mp4")]
        chain.append("[1:v]fps=30,setsar=1[pan]")
        if shot.still:
            # The pane is a locked still of a persisted run rather than live footage, so it
            # comes from its own input and the master is used only for the establish.
            inputs += ["-loop", "1", "-t", f"{shot.want:.3f}", "-i", str(RAW / shot.still)]
            sx, sy, sw, sh = scale2(shot.still_crop)
            chain.append(
                f"[2:v]fps=30,scale={W * 2}:{H * 2}:flags=bicubic,setsar=1,"
                f"crop={sw}:{sh}:{sx}:{sy},scale={PANE_W * 2}:{H * 2}:flags=lanczos[pane]"
            )
        if shot.panel_mode == "hold":
            # No entrance: the panel is already there from the previous shot.
            chain.append(
                f"[m]crop={cw}:{ch}:{cx}:{cy},scale={PANE_W * 2}:{H * 2}:flags=lanczos,setsar=1[pane]"
            )
            chain.append("[pan][pane]hstack=inputs=2[full]")
        else:
            hx, hy, hw, hh = scale2(shot.highlight)
            if shot.still:
                chain.append(
                    f"[m]drawbox=x={hx}:y={hy}:w={hw}:h={hh}:color={HL_COLOR}@1:thickness=8"
                    f":enable='between(t,{EST},{SPLIT_AT + MOVE:.3f})',"
                    f"trim=0:{SPLIT_AT + MOVE:.3f},setpts=PTS-STARTPTS[wide]"
                )
            else:
                chain.append("[m]split=2[m1][m2]")
                chain.append(
                    f"[m1]drawbox=x={hx}:y={hy}:w={hw}:h={hh}:color={HL_COLOR}@1:thickness=8"
                    f":enable='between(t,{EST},{SPLIT_AT + MOVE:.3f})',"
                    f"trim=0:{SPLIT_AT + MOVE:.3f},setpts=PTS-STARTPTS[wide]"
                )
                chain.append(
                    f"[m2]crop={cw}:{ch}:{cx}:{cy},scale={PANE_W * 2}:{H * 2}:flags=lanczos,"
                    f"trim=start={SPLIT_AT:.3f},setpts=PTS-STARTPTS,setsar=1[pane]"
                )
            chain.append("[pan][pane]hstack=inputs=2[split]")
            chain.append(
                f"[wide][split]xfade=transition=fade:duration={MOVE}:offset={SPLIT_AT:.3f}[full]"
            )
        chain.append(f"[full]scale={W}:{H}:flags=lanczos[cam]")
        return inputs, chain, "cam"

    body = "m"
    if shot.highlight:
        hx, hy, hw, hh = scale2(shot.highlight)
        off = EST + LEAD + MOVE + 0.25  # the highlight clears a beat after the move lands
        chain.append(
            f"[{body}]drawbox=x={hx}:y={hy}:w={hw}:h={hh}:color={HL_COLOR}@1:thickness=8"
            f":enable='between(t,{EST},{off:.3f})'[hl]"
        )
        body = "hl"

    if shot.crop:
        cx, cy, cw, ch = scale2(shot.crop)
        z0 = EST + LEAD
        zoom = round(W / (cw / 2), 6)
        # Eased push-in. `on/30` is output time; the eased 0..1 progress drives z, x and y
        # together. At progress 0 the frame is untouched; at 1 the visible region is exactly
        # the crop — and because the expression then evaluates to the same constants every
        # frame, the hold that follows is bit-identical frame to frame.
        u = f"clip((on/30-{z0})/{MOVE},0,1)"
        e = f"if(lt({u},0.5),4*pow({u},3),1-pow(-2*{u}+2,3)/2)"
        chain.append(
            f"[{body}]zoompan=z='1+({zoom}-1)*({e})':x='{cx}*({e})':y='{cy}*({e})'"
            f":d=1:s={W}x{H}:fps=30[cam]"
        )
    else:
        # Some screens already span the full width of the master, so any push-in would clip
        # the very thing being narrated — the highlight alone directs the eye.
        chain.append(f"[{body}]scale={W}:{H}:flags=lanczos[cam]")

    return inputs, chain, "cam"


def main() -> int:
    paragraphs = align.read_paragraphs(MEDIA / "narration.txt")
    if len(paragraphs) != len(SHOTS):
        raise SystemExit(f"{len(paragraphs)} narration paragraphs but {len(SHOTS)} shots")

    tempo = build_audio()

    # Panels and chips are cut against the RAW narration, because each shot is rendered at
    # its raw segment length and the whole picture is retimed by `tempo` at the very end.
    words = align.align(
        paragraphs,
        align.transcribe(BUILD / "audio_raw.wav", align.api_key(), BUILD / "words_raw.json"),
        probe(BUILD / "audio_raw.wav"),
    )

    clock = 0.0
    for shot in SHOTS:
        shot.want = probe(RAW / f"seg_{shot.n}.wav")
        shot.start = clock
        clock += shot.want

    print("== fitting clips to narration ==")
    failed = False
    for shot in SHOTS:
        clip = RAW / f"clip{shot.n}.webm"
        if not clip.is_file():
            print(f"  MISSING {clip}")
            failed = True
            continue
        usable = max(0.0, (probe(clip) - shot.trim) / shot.speed)
        if usable + 0.05 < shot.want:
            # Deliberately fatal. Padding here is what broke v1.
            print(f"  clip{shot.n} TOO SHORT: {usable:.1f}s usable < {shot.want:.1f}s narration")
            failed = True
    if failed:
        raise SystemExit("ABORTING: fix the clips above before assembling.")

    # A panel's timeline is continuous even where it spans two shots, so it is measured once
    # and each shot takes the slice it needs.
    for panel, anchors in PANEL_STATES.items():
        members = [shot for shot in SHOTS if shot.panel == panel]
        first = members[0]
        origin = first.start + SPLIT_AT
        length = sum(shot.want for shot in members) - SPLIT_AT
        offset = 0.0
        for shot in members:
            shot.panel_offset = offset
            shot.panel_len = shot.want - (SPLIT_AT if shot is first else 0.0)
            offset += shot.panel_len
        times = [0.0]
        for anchor in anchors[1:]:
            times.append(round(align.find(words, anchor[0], anchor[1]) - origin, 3))
        if times != sorted(times):
            raise SystemExit(f"panel {panel} states are out of order: {times}")
        whole = BUILD / f"panel_{panel}.mp4"
        panel_video(panel, times, length, whole)
        print(f"  panel {panel}: {length:.2f}s, states at {[f'{t:.1f}' for t in times]}")
        for shot in members:
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{shot.panel_offset:.3f}",
                 "-i", str(whole), "-t", f"{shot.panel_len:.3f}", "-c:v", "libx264",
                 "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                 str(BUILD / f"panel_{panel}_{shot.n}.mp4")])

    listing = BUILD / "video_list.txt"
    entries = []
    for shot in SHOTS:
        inputs, chain, label = shot_filters(shot)
        args = ["ffmpeg", "-y", "-v", "error", "-ss", str(shot.trim),
                "-i", str(RAW / f"clip{shot.n}.webm"), *inputs]

        # Borders step between the things the narration names, one at a time, on a locked
        # picture. Same grammar as the camera highlights: the border arrives just before the
        # word, so the eye is already on the right chip when it is named.
        if shot.borders:
            marks = [align.find(words, shot.n_paragraph, phrase) - shot.start - BORDER_LEAD
                     for phrase, _ in shot.borders]
            for index, (_, (bx, by, bw, bh)) in enumerate(shot.borders):
                start = max(0.0, marks[index])
                end = marks[index + 1] if index + 1 < len(marks) else shot.want
                chain.append(
                    f"[{label}]drawbox=x={bx}:y={by}:w={bw}:h={bh}:color={HL_COLOR}@1"
                    f":thickness=4:enable='between(t,{start:.3f},{end:.3f})'[bd{index}]"
                )
                label = f"bd{index}"

        if shot.chip:
            at = (shot.chip_at if isinstance(shot.chip_at, (int, float))
                  else align.find(words, *shot.chip_at) - shot.start)
            hold = shot.chip_hold if shot.chip_hold is not None else CHIP_HOLD
            # Count real inputs: `inputs` is not a list of pairs any more, because a still
            # carries -loop and -t alongside its -i.
            index = inputs.count("-i") + 1
            # `-loop 1` matters: a bare image input is a single frame at t=0, which the fade
            # filter renders at alpha 0 and overlay then repeats forever — a chip that never
            # appears, silently.
            args += ["-loop", "1", "-t", f"{shot.want:.3f}", "-i",
                     str(PANELS / f"chip_{shot.chip}.png")]
            chain.append(
                f"[{index}:v]fps=30,scale=iw/2:ih/2,format=rgba,setsar=1,"
                f"fade=t=in:st={at:.3f}:d={CHIP_FADE}:alpha=1,"
                f"fade=t=out:st={at + hold:.3f}:d={CHIP_FADE}:alpha=1[chip]"
            )
            chain.append(f"[{label}][chip]overlay={shot.chip_xy[0]}:{shot.chip_xy[1]}[cam2]")
            label = "cam2"

        out = BUILD / f"v_{shot.n}.mp4"
        args += ["-filter_complex", ";".join(chain), "-map", f"[{label}]",
                 "-t", f"{shot.want:.3f}", "-an",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                 str(out)]
        run(args)
        entries.append(f"file 'v_{shot.n}.mp4'\n")
        move = (f"split-screen panel {shot.panel} ({shot.panel_mode})" if shot.panel
                else f"zoom onto {shot.crop}" if shot.crop
                else "full frame, highlight only" if shot.highlight
                else "full frame, no move")
        print(f"  clip{shot.n} -> {shot.want:6.2f}s  {move}")
    listing.write_text("".join(entries))

    print("== concatenating ==")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(BUILD / "video.mp4")])

    # Picture is retimed by the same factor as the voice so the two stay locked. The per-shot
    # intermediates are cut at crf 19 so nothing is thrown away before this point; only the
    # final pass is quantised harder.
    run(["ffmpeg", "-y", "-v", "error", "-i", str(BUILD / "video.mp4"),
         "-vf", f"setpts=PTS/{tempo:.6f}", "-an", "-c:v", "libx264", "-preset", "slow",
         "-crf", "23", "-pix_fmt", "yuv420p", str(BUILD / "video_fit.mp4")])

    print("== muxing ==")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(BUILD / "video_fit.mp4"),
         "-i", str(BUILD / "audio.wav"), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(OUTPUT)])

    duration = probe(OUTPUT)
    print(json.dumps({"file": OUTPUT.name, "seconds": round(duration, 3),
                      "limit": 180, "under_limit": duration < 180}, indent=1))
    if duration >= 180:
        raise SystemExit("OVER THE 3:00 HARD LIMIT — trim narration and re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
