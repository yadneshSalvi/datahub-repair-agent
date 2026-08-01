#!/usr/bin/env bash
# Assemble the demo video: each clip is fitted to its narration segment, then the
# concatenated video is muxed with the concatenated narration.
#
# Fitting rule: clips are recorded slightly longer than needed, so we take the TAIL of each
# clip (the settled state) rather than the head (which contains page load and layout shift).
set -euo pipefail
cd "$(dirname "$0")"

RAW=raw
OUT=build
mkdir -p "$OUT"

# clip -> narration segment (1:1)
CLIPS=(clip01 clip02 clip03 clip04 clip05 clip06 clip07 clip08 clip09 clip10)

echo "== fitting clips to narration durations =="
: > "$OUT/video_list.txt"
: > "$OUT/audio_list.txt"
total=0
for i in "${!CLIPS[@]}"; do
  n=$(printf "%02d" $((i + 1)))
  clip="${CLIPS[$i]}"
  wav="$RAW/seg_$n.wav"
  want=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$wav")
  have=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$RAW/$clip.webm")

  # Take the tail when the clip is long enough; otherwise hold the final frame to fill.
  start=$(python3 -c "print(max(0.0, $have - $want))")
  ffmpeg -y -v error -ss "$start" -i "$RAW/$clip.webm" \
    -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x08090b,fps=30,tpad=stop_mode=clone:stop_duration=6" \
    -t "$want" -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$OUT/v_$n.mp4"

  echo "file 'v_$n.mp4'" >> "$OUT/video_list.txt"
  echo "file '../$RAW/seg_$n.wav'" >> "$OUT/audio_list.txt"
  total=$(python3 -c "print(round($total + $want, 2))")
  printf "  %s -> seg %s  %6.2fs\n" "$clip" "$n" "$want"
done
echo "  total: ${total}s"

echo "== concatenating =="
ffmpeg -y -v error -f concat -safe 0 -i "$OUT/video_list.txt" -c copy "$OUT/video.mp4"
ffmpeg -y -v error -f concat -safe 0 -i "$OUT/audio_list.txt" -c:a pcm_s16le "$OUT/audio.wav"

echo "== muxing =="
ffmpeg -y -v error -i "$OUT/video.mp4" -i "$OUT/audio.wav" \
  -c:v copy -c:a aac -b:a 192k -shortest schema-drift-auto-repair-agent.mp4

ffprobe -v error -show_entries format=duration:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 schema-drift-auto-repair-agent.mp4
echo "DONE: media/schema-drift-auto-repair-agent.mp4"
