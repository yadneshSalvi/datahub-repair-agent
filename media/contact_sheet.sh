#!/usr/bin/env bash
# Build a contact sheet of the finished video so a human (or main) can eyeball every beat
# without scrubbing a player.
#
# Default is one frame every 5s, which is what surfaced v1's dead air: eight consecutive
# near-identical tiles is what a 40-second frozen shot looks like on a sheet.
#
# Usage: contact_sheet.sh [interval_seconds] [output.png]
set -euo pipefail
cd "$(dirname "$0")"

VIDEO=schema-drift-auto-repair-agent.mp4
INTERVAL="${1:-5}"
OUT="${2:-build/contact-sheet.png}"
COLS=6

[ -f "$VIDEO" ] || { echo "$VIDEO missing; run assemble.sh first."; exit 1; }
mkdir -p "$(dirname "$OUT")"

duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
count=$(python3 -c "import math;print(int(math.floor($duration / $INTERVAL)))")
rows=$(python3 -c "import math;print(math.ceil($count / $COLS))")

# No drawtext: this ffmpeg build ships without it. Tiles are read left-to-right, top-to-bottom,
# so tile N (0-based) is at N * INTERVAL seconds — printed below for reference.
ffmpeg -y -v error -i "$VIDEO" \
  -vf "fps=1/$INTERVAL,scale=480:-1,tile=${COLS}x${rows}:margin=4:padding=4" \
  -frames:v 1 "$OUT"

echo "wrote $OUT — ${count} tiles at ${INTERVAL}s intervals (${duration}s total), ${COLS} per row"
echo "tile N (0-based, reading left-to-right) = N * ${INTERVAL}s"
