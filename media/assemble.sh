#!/usr/bin/env bash
# Assemble the demo: fit each clip to its narration segment, then mux.
#
# What changed from v1, and why:
#
# * v1 stretched a too-short clip to its narration length with
#   `tpad=stop_mode=clone`, i.e. by FREEZING the final frame. That is what produced the
#   30-40 second motionless stretches the user rejected. Freezing is now impossible:
#   capture.sh guarantees every clip outlasts its segment, and a clip that still comes up
#   short is reported as an error rather than padded.
#
# * v1 took the TAIL of each clip to dodge the page load at the head. That worked, but it
#   also threw away the scripted motion and landed on the settled, static end state. v2
#   instead drops exactly SETTLE seconds off the head (the scripted dead lead-in) and keeps
#   the motion that follows.
#
# * Close-ups are made here, not in the browser: Playwright's video pipeline ignores CSS
#   zoom, so each shot is filmed wide at native 1920x1080 and CROP=x:y:w:h lifts a window of
#   real pixels out of it. 1280x720 out of 1920x1080 is a 1.5x enlargement and stays sharp.
#
# * SPEED lets a shot that had to be filmed in real time (the agent run) be compressed to
#   its narration length without dropping any of the events it shows.
set -euo pipefail
cd "$(dirname "$0")"

RAW=raw
OUT=build
SETTLE="${SETTLE:-3}"          # must match capture.sh
W=1920
H=1080
mkdir -p "$OUT"

# clip | crop | speed factor (1 = real time) | head trim in seconds (default SETTLE)
#
# The trim override exists because DataHub's own UI is slower than this app's: on the
# post-repair Schema tab its column table takes ~5s to paint, so the default 3s settle still
# left two blank white frames at the head of shot 13. That shot is captured with SETTLE=8 and
# trimmed by 8 here. Everything else settles well inside 3s.
#
# CROP IS ffmpeg ORDER: w:h:x:y — width and height FIRST, then the top-left corner.
# Writing it as x:y:w:h silently "works" and yields a tiny sliver from the wrong corner
# (e.g. 40:180:1600:900 crops a 40x180 chip at 1600,900), which renders as a black frame
# with a thin bar. It costs a full assemble+review cycle to spot, so keep this note.
#
# Crops are chosen so the thing the narration is pointing at fills the frame:
#   01/02 stay wide — they are establishing shots of DataHub itself.
#   04/09/10 push in hard, because that is where the unreadable-text complaint came from.
#   05 is filmed for ~84s and compressed to its 23s segment.
#
# Every crop is exactly 16:9 so nothing gets pillarboxed on the way to 1920x1080.
# Handy sizes: 1440x810 = 1.33x, 1280x720 = 1.5x, 1024x576 = 1.875x, 960x540 = 2x.
#
# These windows are MEASURED, not guessed: a first pass of eyeballed crops put several shots
# on empty background, because the page scrolls during a shot and the content is not where it
# looks like it should be. Each value below was read off the actual frame the assembler uses
# (SETTLE + segment/2) before being written here. Re-measure after changing any choreography.
#
# The 5th field is a slow CAMERA PAN, "dx,dy" in source pixels across the whole shot.
#
# It is there because several screens have nothing that can move. /impact and /writeback have
# no scrollable container at all at 1080p — the page simply fits — so once the scripted clicks
# are done, the only thing changing is the pointer, and a 16-second stretch of that reads as
# dead air. A gentle drift of the crop window keeps every pixel in motion. It is a camera
# move, not a change to anything the app is showing.
SHOTS=(
  # 01/02/13 are DataHub's own near-white pages. A pan across large flat areas barely
  # registers as pixel change, so they are framed tighter (which also enlarges the text) and
  # panned further than the dark app screens need.
  # 01/02 are shot against the PRISTINE catalog (post /api/reset, pre-drift) so the opening
  # genuinely shows order_placed_at un-renamed, no drift tags and no repair docs. An earlier
  # cut re-shot these after the run had completed, which made the "before" and the closing
  # "after" visually identical and hid the whole transformation. Never re-shoot these while
  # a repair is applied. SETTLE=6 on capture, trimmed by 6 here — DataHub paints slowly.
  # 01 pans mostly vertically: the Name column starts at x=80 in the source, so any horizontal
  # travel past ~70 clips the very column names the shot exists to show.
  "01|1400:788:40:150|1|6|60,260"
  "02|1000:562:200:440|1|6|200,160"
  "03|1400:788:260:180|1||170,70"
  "04|1440:810:280:80|1||150,110"
  "05|980:552:940:400|3.4||-170,90"
  "06|1400:788:260:60|1||190,140"
  "07|1300:732:260:60|1||230,180"
  # trim 5 (not 3): the scroll-and-click choreography runs in the first few seconds, and at
  # the default trim the evidence drawer opened well after the narration had cued it.
  "08|960:540:940:120|1|5|-190,220"
  "09|1100:620:580:90|1||180,180"
  "10|1228:692:272:388|1||260,-180"
  # The PR heading ("Repair shop_prod.raw.orders timestamp column rename drift") starts at
  # source x~190 while the lineage diagram runs to ~1520, which will not fit in a 1120-wide
  # window. Widened to 1360 (1.41x instead of 1.71x) so the whole title is readable on the
  # "it opens a real pull request" line.
  "11|1360:765:160:90|1||40,180"
  "12|1450:816:270:100|1||170,140"
  # Deliberately the SAME framing and pan as shot 01, so the close is a match cut on the open:
  # identical view of the same column list, pristine at 0:08 and repaired at 2:46. The wider
  # horizontal pan this used to have swung the Name column out of frame, hiding the one thing
  # the shot is meant to prove.
  "13|1400:788:40:150|1|8|60,260"
)

echo "== fitting clips to narration =="
: > "$OUT/video_list.txt"
: > "$OUT/audio_list.txt"
total=0
fail=0

for entry in "${SHOTS[@]}"; do
  IFS='|' read -r n crop speed trim pan <<< "$entry"
  trim="${trim:-$SETTLE}"
  clip="$RAW/clip$n.webm"
  wav="$RAW/seg_$n.wav"
  [ -f "$clip" ] || { echo "  MISSING $clip"; fail=1; continue; }
  [ -f "$wav" ]  || { echo "  MISSING $wav";  fail=1; continue; }

  want=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")
  have=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$clip")
  # Usable footage = everything after the scripted settle window, sped up if asked.
  usable=$(python3 -c "print(max(0.0, ($have - $trim) / $speed))")

  short=$(python3 -c "print('yes' if $usable + 0.05 < $want else 'no')")
  if [ "$short" = "yes" ]; then
    # Deliberately fatal. Padding here is what broke v1.
    printf '  clip%s TOO SHORT: %.1fs usable < %.1fs narration — re-shoot it\n' "$n" "$usable" "$want"
    fail=1
  fi

  filters="fps=30"
  if [ "$crop" != "-" ]; then
    IFS=':' read -r cw ch cx cy <<< "$crop"
    if [ -n "$pan" ]; then
      # crop can move its window per frame but cannot resize it, so the camera pans rather
      # than pushes in. `t` runs 0..span because -ss precedes -i and rebases timestamps;
      # span is the INPUT seconds consumed, i.e. before any setpts speed-up.
      #
      # The pan is CENTRED on the framing (-d/2 .. +d/2) rather than starting from it.
      # Starting at the measured window and drifting away from it pushed content toward one
      # edge and left a third of the frame empty by the end of the longer shots.
      IFS=',' read -r dx dy <<< "$pan"
      span=$(python3 -c "print(round($want * $speed, 3))")
      read -r x0 x1 y0 y1 <<< "$(python3 -c "
clamp = lambda v, hi: max(0, min(int(round(v)), hi))
print(clamp($cx - $dx/2, 1920-$cw), clamp($cx + $dx/2, 1920-$cw),
      clamp($cy - $dy/2, 1080-$ch), clamp($cy + $dy/2, 1080-$ch))")"
      filters="crop=$cw:$ch:'$x0+($x1-$x0)*min(t/$span,1)':'$y0+($y1-$y0)*min(t/$span,1)',$filters"
    else
      filters="crop=$crop,$filters"
    fi
  fi
  [ "$speed" != "1" ] && filters="$filters,setpts=PTS/$speed"
  filters="$filters,scale=$W:$H:force_original_aspect_ratio=decrease:flags=lanczos"
  filters="$filters,pad=$W:$H:(ow-iw)/2:(oh-ih)/2:color=0x08090b"

  ffmpeg -y -v error -ss "$trim" -i "$clip" \
    -vf "$filters" -t "$want" -an \
    -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p "$OUT/v_$n.mp4"

  echo "file 'v_$n.mp4'" >> "$OUT/video_list.txt"
  echo "file '../$RAW/seg_$n.wav'" >> "$OUT/audio_list.txt"
  total=$(python3 -c "print(round($total + $want, 2))")
  printf '  clip%s -> %6.2fs  (had %5.1fs usable%s)\n' "$n" "$want" "$usable" \
    "$([ "$speed" != 1 ] && echo " @${speed}x" || true)"
done

[ "$fail" = "1" ] && { echo "ABORTING: fix the clips above before assembling."; exit 1; }
echo "  narration total: ${total}s"

echo "== concatenating =="
ffmpeg -y -v error -f concat -safe 0 -i "$OUT/video_list.txt" -c copy "$OUT/video.mp4"
ffmpeg -y -v error -f concat -safe 0 -i "$OUT/audio_list.txt" -c:a pcm_s16le "$OUT/audio_raw.wav"

# Tempo fit. The script is written to be as informative as 3:00 allows, so it lands slightly
# long; a small speed-up is far less damaging than cutting explanation a first-time viewer
# needs. Clamped, because past ~1.15 the voice starts to sound harried.
TARGET="${TARGET:-171}"
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/audio_raw.wav")
tempo=$(python3 -c "print(round(min(1.15, max(1.0, $dur / $TARGET)), 4))")
echo "== tempo fit: ${dur}s -> target ${TARGET}s (atempo $tempo) =="
ffmpeg -y -v error -i "$OUT/audio_raw.wav" -filter:a "atempo=$tempo" "$OUT/audio.wav"

# Video must be retimed by the same factor so picture and voice stay locked.
#
# The per-shot intermediates are cut at crf 19 so nothing is thrown away before the pans and
# speed ramps are applied; only this final pass is quantised harder. crf 23 measured visually
# identical on the diff and validation text (the smallest type in the video) while taking the
# deliverable from 38 MB to 24 MB, which matters for a file that lives in the repo.
ffmpeg -y -v error -i "$OUT/video.mp4" -vf "setpts=PTS/$tempo" -an \
  -c:v libx264 -preset slow -crf "${FINAL_CRF:-23}" -pix_fmt yuv420p "$OUT/video_fit.mp4"

echo "== muxing =="
ffmpeg -y -v error -i "$OUT/video_fit.mp4" -i "$OUT/audio.wav" \
  -c:v copy -c:a aac -b:a 192k -shortest schema-drift-auto-repair-agent.mp4

ffprobe -v error -show_entries format=duration:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 schema-drift-auto-repair-agent.mp4
echo "DONE: media/schema-drift-auto-repair-agent.mp4"
