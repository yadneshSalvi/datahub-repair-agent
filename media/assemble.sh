#!/usr/bin/env bash
# Assemble the demo: fit each clip to its narration segment, apply the camera treatment,
# then mux.
#
# CAMERA GRAMMAR. This replaced a continuous slow pan, which read as shaky and slid text off
# the edge of frame — the drifting camera was rejected on review. Per shot:
#
#   1. ESTABLISH   full frame, pixel-locked, 1.8s
#   2. HIGHLIGHT   a violet rectangle is drawn around the region about to be discussed,
#                  0.8s BEFORE the move, so the eye finds it first
#   3. ZOOM        1.0s, ease-in-out cubic, full frame -> target crop
#   4. HOLD        that crop, perfectly static, for the rest of the shot
#
# There is deliberately AT MOST ONE camera move per shot, and every cut happens at full frame,
# so a cut is never made mid-move. Long static holds are correct here: the UI's own motion
# (streaming events, the cursor, diffs appearing, the page scrolling at reading speed) carries
# the shot. NO pans, NO drift, NO Ken Burns anywhere.
#
# Other things worth knowing before changing anything:
#
# * v1 stretched a short clip to its narration length with `tpad=stop_mode=clone`, i.e. by
#   FREEZING the last frame, which produced 30-40 second motionless stretches. Freezing is
#   impossible now: a clip shorter than its segment is a hard error, not something to pad.
# * Playwright's video pipeline ignores CSS zoom, so close-ups are made HERE, out of real
#   pixels, never by zooming the browser.
# * The move is computed on a 2x master (3840x2160) and rounded only at output, so it is
#   sub-pixel smooth rather than stepping.
set -euo pipefail
cd "$(dirname "$0")"

RAW=raw
OUT=build
W=1920
H=1080
HL_COLOR=0x6366f1              # the app's own accent violet; reads on the dark UI and on white
EST=1.8                        # full-frame establish before anything moves
LEAD=0.8                       # highlight appears this long before the zoom starts
ZOOM_T=1.0                     # zoom duration
mkdir -p "$OUT"

# clip | trim | speed | highlight x:y:w:h | crop x:y:w:h      (all in 1920x1080 master coords)
#
# "-" for the last two fields means NO camera move: the shot stays full frame throughout.
# Every rectangle below was measured off the actual master frame for that shot, so the
# highlight lands on a real UI region rather than floating over nothing.
#
# Shot 06 is deliberately a full-frame establish of the graph, so 06 and 07 read as one
# continuous wide view with a single push-in during 07, rather than two moves back to back.
# Shots 01 and 13 share a crop on purpose: the close is a match cut on the open.
SHOTS=(
  "01|6|1|68:296:1240:360|40:95:1360:765"
  "02|6|1|196:506:588:304|0:350:1100:619"
  # Highlight is the Rename card ONLY. A wider box spilled into the neighbouring Retype
  # card, which is not what the line is about, and the drift banner does not exist yet at
  # this point in the shot — it appears when the card is clicked.
  "03|3|1|268:196:545:200|136:40:1000:562"
  "04|3|1|275:428:1615:56|-"
  "05|3|3.4|1496:480:400:592|840:470:1080:608"
  "06|3|1|-|-"
  "07|3|1|268:172:1288:360|180:0:1460:821"
  "08|5|1|1540:56:368:572|920:60:1000:563"
  "09|3|1|556:160:908:320|460:0:1100:619"
  "10|3|1|275:550:1350:450|200:236:1500:844"
  "11|3|1|-|-"
  "12|3|1|275:145:1610:545|-"
  "13|8|1|68:296:1240:360|40:95:1360:765"
)

echo "== fitting clips to narration =="
: > "$OUT/video_list.txt"
: > "$OUT/audio_list.txt"
total=0
fail=0

for entry in "${SHOTS[@]}"; do
  IFS='|' read -r n trim speed hl crop <<< "$entry"
  clip="$RAW/clip$n.webm"
  wav="$RAW/seg_$n.wav"
  [ -f "$clip" ] || { echo "  MISSING $clip"; fail=1; continue; }
  [ -f "$wav" ]  || { echo "  MISSING $wav";  fail=1; continue; }

  want=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")
  have=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$clip")
  usable=$(python3 -c "print(max(0.0, ($have - $trim) / $speed))")

  if [ "$(python3 -c "print('1' if $usable + 0.05 < $want else '0')")" = "1" ]; then
    # Deliberately fatal. Padding here is what broke v1.
    printf '  clip%s TOO SHORT: %.1fs usable < %.1fs narration — re-shoot it\n' "$n" "$usable" "$want"
    fail=1
  fi

  # setpts first so the camera timeline below is expressed in OUTPUT seconds even for the
  # time-compressed run shot; fps after it, so zoompan's frame counter maps cleanly to time.
  filters=""
  [ "$speed" != "1" ] && filters="setpts=PTS/$speed,"
  filters="${filters}fps=30,scale=$((W*2)):$((H*2)):flags=bicubic"

  if [ "$crop" = "-" ]; then
    # No camera move. Some screens (the two schema panels, the six write-back cards) already
    # span the full width of the master, so any push-in would clip the very thing being
    # narrated — for those the highlight alone directs the eye and the camera stays put.
    if [ "$hl" != "-" ]; then
      IFS=':' read -r hx hy hw hh <<< "$hl"
      hl_off=$(python3 -c "print(round($EST + $LEAD + $ZOOM_T + 0.25, 3))")
      filters="$filters,drawbox=x=$((hx*2)):y=$((hy*2)):w=$((hw*2)):h=$((hh*2))"
      filters="$filters:color=$HL_COLOR@1:thickness=8:enable='between(t,$EST,$hl_off)'"
      move="full frame, highlight only"
    else
      move="full frame, no move"
    fi
    filters="$filters,scale=$W:$H:flags=lanczos"
  else
    IFS=':' read -r cx cy cw ch <<< "$crop"
    IFS=':' read -r hx hy hw hh <<< "$hl"
    z0=$(python3 -c "print(round($EST + $LEAD, 3))")
    z1=$(python3 -c "print(round($EST + $LEAD + $ZOOM_T, 3))")
    hl_off=$(python3 -c "print(round($z1 + 0.25, 3))")
    Z=$(python3 -c "print(round($W / $cw, 6))")

    # The highlight is drawn on the 2x master BEFORE the zoom, so it scales with the move
    # rather than sitting on top of it, and it clears a beat after the move lands.
    filters="$filters,drawbox=x=$((hx*2)):y=$((hy*2)):w=$((hw*2)):h=$((hh*2))"
    filters="$filters:color=$HL_COLOR@1:thickness=8:enable='between(t,$EST,$hl_off)'"

    # Eased push-in. `on/30` is output time; the eased 0..1 progress drives z, x and y
    # together. At progress 0 the frame is untouched; at 1 the visible region is exactly the
    # crop — and because the expression then evaluates to the same constants every frame, the
    # hold that follows is bit-identical frame to frame.
    u="clip((on/30-$z0)/$ZOOM_T,0,1)"
    e="if(lt($u,0.5),4*pow($u,3),1-pow(-2*$u+2,3)/2)"
    filters="$filters,zoompan=z='1+($Z-1)*($e)':x='$((cx*2))*($e)':y='$((cy*2))*($e)'"
    filters="$filters:d=1:s=${W}x${H}:fps=30"
    move="zoom ${Z}x at ${z0}s onto ${cw}x${ch}+${cx}+${cy}"
  fi

  ffmpeg -y -v error -ss "$trim" -i "$clip" \
    -vf "$filters" -t "$want" -an \
    -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p "$OUT/v_$n.mp4"

  echo "file 'v_$n.mp4'" >> "$OUT/video_list.txt"
  echo "file '../$RAW/seg_$n.wav'" >> "$OUT/audio_list.txt"
  total=$(python3 -c "print(round($total + $want, 2))")
  printf '  clip%s -> %6.2fs  %s\n' "$n" "$want" "$move"
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
# The per-shot intermediates are cut at crf 19 so nothing is thrown away before this point;
# only the final pass is quantised harder. crf 23 measured visually identical on the diff and
# validation text (the smallest type in the video) at two thirds the file size.
ffmpeg -y -v error -i "$OUT/video.mp4" -vf "setpts=PTS/$tempo" -an \
  -c:v libx264 -preset slow -crf "${FINAL_CRF:-23}" -pix_fmt yuv420p "$OUT/video_fit.mp4"

echo "== muxing =="
ffmpeg -y -v error -i "$OUT/video_fit.mp4" -i "$OUT/audio.wav" \
  -c:v copy -c:a aac -b:a 192k -shortest schema-drift-auto-repair-agent.mp4

ffprobe -v error -show_entries format=duration:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 schema-drift-auto-repair-agent.mp4
echo "DONE: media/schema-drift-auto-repair-agent.mp4"
