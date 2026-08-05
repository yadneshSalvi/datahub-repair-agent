#!/usr/bin/env bash
# Capture the v2 demo footage: one clip per narration paragraph.
#
# Design notes that matter if you change anything here:
#
# 1. `agent-browser record start` creates a FRESH browser context and re-navigates, so the
#    page load always happens *inside* the recording. Every clip therefore opens with a fixed
#    SETTLE window during which nothing is scripted; assemble.sh drops exactly that many
#    seconds off the head. That is how the loading skeletons stay out of the final cut.
#    It also means the injected cursor is destroyed by `record start` and must be re-injected
#    afterwards — doing it before is silently useless.
#
# 2. There is NO browser zoom here, deliberately. Playwright's video pipeline ignores CSS
#    `zoom` on both <html> and <body> — a screenshot shows the zoom, the recorded frame does
#    not (verified both ways). So every shot is captured at native 1920x1080 and close-ups are
#    made in assemble.sh by cropping a window of REAL pixels and scaling it up. Cropping
#    1280x720 out of a 1920x1080 master is a 1.5x enlargement of native pixels, which stays
#    legible; faking it with CSS would have silently produced un-zoomed footage.
#
# 3. Every shot runs LONGER than its narration segment: each motion script ends with
#    `__demo.until(TARGET)`, which keeps the pointer drifting until the shot has met its
#    length. v1 stretched short clips by freezing the last frame, which is exactly what
#    produced its 30-40 second static stretches. A clip can now never be too short, and
#    never has to be frozen.
set -euo pipefail
cd "$(dirname "$0")"

MEDIA="$PWD"
RAW="$MEDIA/raw"
SESSION="repair-video"
API="http://127.0.0.1:8002"
APP="http://localhost:3002"
DH="http://localhost:9002"
ORDERS_URN="urn%3Ali%3Adataset%3A%28urn%3Ali%3AdataPlatform%3Asnowflake%2Cshop_prod.raw.orders%2CPROD%29"
SETTLE="${SETTLE:-3}"        # seconds of dead lead-in, trimmed by assemble.sh
SCENARIO="rename_order_placed_at"

mkdir -p "$RAW"

ab() { agent-browser --session "$SESSION" "$@"; }
inject() { ab eval --stdin < "$MEDIA/demo-cursor.js" >/dev/null 2>&1 || true; }
js() { ab eval --stdin >/dev/null; }
banner() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# Extend a shot to `total` ms of elapsed time, in chunks.
#
# One `eval` may not block for long: the agent-browser daemon gives up on a call that runs
# past its read timeout and returns "Resource temporarily unavailable (os error 35)", which
# killed the first capture attempt on the 84-second run shot. Because __demo.mark() lives in
# page state, calling until() repeatedly with a rising deadline is equivalent to one long
# call, but every individual round-trip stays short.
CHUNK_MS=12000
hold() {
  local total="$1" box="${2:-null}" t=0
  while [ "$t" -lt "$total" ]; do
    t=$((t + CHUNK_MS)); [ "$t" -gt "$total" ] && t="$total"
    ab eval "__demo.until($t, $box)" >/dev/null
  done
}

prewarm() {
  ab open "$1" >/dev/null
  ab wait --load networkidle >/dev/null 2>&1 || true
  sleep 1
}

start_clip() {
  # A capture that dies mid-shot leaves the recorder armed, and every subsequent
  # `record start` then fails with "Recording already active". Clear it first so one bad
  # shot cannot poison the rest of the run.
  ab record stop >/dev/null 2>&1 || true
  ab record start "$RAW/clip$1.webm" >/dev/null
  ab wait --load networkidle >/dev/null 2>&1 || true
  inject
  ab eval "__demo.settled()" >/dev/null 2>&1 || true
  sleep "$SETTLE"
  ab eval "__demo.mark(); 1" >/dev/null
}

stop_clip() {
  ab record stop >/dev/null
  local d
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$RAW/clip$1.webm" 2>/dev/null || echo "?")
  echo "   saved clip$1.webm  ${d}s"
}

# ---------------------------------------------------------------- demo state

reset_demo() {
  banner "reset demo (revert drift, re-seed catalog)"
  curl -s -m 240 -X POST "$API/api/reset" >/dev/null || true
  sleep 3
}

apply_drift() {
  banner "apply drift $SCENARIO"
  curl -s -m 120 -X POST "$API/api/scenarios/$SCENARIO/apply" >/dev/null
  sleep 2
}

wait_for_run() {
  printf '   waiting for the run to finish'
  for _ in $(seq 1 80); do
    local st
    st=$(curl -s -m 20 "$API/api/runs/$1" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "?")
    [ "$st" = "succeeded" ] && { echo " succeeded."; return 0; }
    [ "$st" = "failed" ] && { echo " FAILED."; return 1; }
    printf '.'
    sleep 10
  done
  echo " timed out."; return 1
}

datahub_login() {
  ab open "$DH" >/dev/null
  ab wait --load networkidle >/dev/null 2>&1 || true
  if ab get url | grep -q '/login'; then
    banner "logging into DataHub"
    ab find placeholder "Enter username" fill datahub >/dev/null 2>&1 || true
    ab eval "(()=>{const p=document.querySelector('input[type=password]');if(p){const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(p,'datahub');p.dispatchEvent(new Event('input',{bubbles:true}));}return 1})()" >/dev/null
    ab find role button click --name "Login" >/dev/null 2>&1 || true
    ab wait --load networkidle >/dev/null 2>&1 || true
    sleep 4
  fi
}

# ---------------------------------------------------------------- shots
# TARGET is narration length + margin, in ms. Cropping happens in assemble.sh.

shot01() { # DataHub: what a catalog is
  banner "shot 01 — DataHub columns (narration 13.7s)"
  prewarm "$DH/dataset/$ORDERS_URN/Schema"
  start_clip 01
  js <<'EOF'
(async () => {
  await __demo.moveTo(320, 300, 700);
  for (const y of [364, 409, 454, 499, 544, 589, 634]) await __demo.moveTo(300 + Math.random() * 60, y, 640);
  await __demo.moveTo(700, 454, 800);
  await __demo.scrollBy(null, 110, 900);
  await __demo.moveTo(1150, 500, 900);
  await __demo.scrollBy(null, -110, 900);
  return 1;
})()
EOF
  hold 17500 '{x:120,y:300,w:1100,h:400}'
  stop_clip 01
}

shot02() { # DataHub: the pipeline map
  banner "shot 02 — DataHub lineage (narration 12.7s)"
  prewarm "$DH/dataset/$ORDERS_URN/Lineage"
  start_clip 02
  js <<'EOF'
(async () => {
  await __demo.moveTo(500, 680, 700);
  for (const p of [[760,670],[880,590],[960,460],[1000,640],[1075,520],[1075,780],[960,890],[700,700]])
    await __demo.moveTo(p[0], p[1], 820);
  return 1;
})()
EOF
  hold 16500 '{x:700,y:420,w:480,h:480}'
  stop_clip 02
}

shot03() { # Control Room: apply the drift
  banner "shot 03 — apply drift (narration 12.8s)"
  prewarm "$APP/"
  start_clip 03
  js <<'EOF'
(async () => {
  const apply = [...document.querySelectorAll('button')].find(b => /apply drift/i.test(b.textContent || ''));
  await __demo.moveTo(560, 380, 800);
  await __demo.moveTo(540, 340, 600);
  if (apply) await __demo.click(apply, 900);
  await __demo.sleep(2200);
  await __demo.moveTo(700, 492, 900);
  await __demo.moveTo(1120, 492, 900);
  return !!apply;
})()
EOF
  hold 16500 '{x:300,y:280,w:1300,h:260}'
  stop_clip 03
}

shot04() { # Schema Diff
  banner "shot 04 — schema diff (narration 9.9s)"
  prewarm "$APP/schema"
  start_clip 04
  js <<'EOF'
(async () => {
  await __demo.moveTo(500, 420, 700);
  await __demo.scrollBy(null, 120, 900);
  await __demo.moveTo(520, 560, 800);
  await __demo.sleep(500);
  await __demo.moveTo(1300, 560, 1000);
  await __demo.sleep(500);
  return 1;
})()
EOF
  hold 13500 '{x:420,y:380,w:1080,h:300}'
  stop_clip 04
}

shot05() { # Control Room: run the agent, MCP chips land
  banner "shot 05 — agent run + MCP chips (narration 23.0s; recorded long, compressed in post)"
  prewarm "$APP/"
  start_clip 05
  # The button is genuinely clicked — the run the viewer sees start is the run every
  # number later in the video is read from.
  js <<'EOF'
(async () => {
  const go = [...document.querySelectorAll('button')].find(b => /run repair agent/i.test(b.textContent || ''));
  await __demo.moveTo(1100, 560, 700);
  if (!go) return false;
  await __demo.click(go, 800);
  return true;
})()
EOF
  sleep 4
  RUN_ID=$(curl -s -m 30 "$API/api/runs" | python3 -c "import json,sys;r=json.load(sys.stdin);print(r[0]['id'] if r else '')")
  echo "   run started: $RUN_ID"
  echo "$RUN_ID" > "$RAW/run_id.txt"
  # Film ~84s of the timeline streaming so the MCP chips genuinely land on camera;
  # assemble.sh compresses it to the 23s segment. hold() does the waiting in short
  # round-trips so the browser daemon never times out mid-shot.
  hold 84000 '{x:1440,y:240,w:440,h:700}'
  stop_clip 05
  wait_for_run "$RUN_ID" || true
}

shot06() { # Impact graph: wide
  banner "shot 06 — impact graph wide (narration 10.7s)"
  prewarm "$APP/impact"
  start_clip 06
  js <<'EOF'
(async () => {
  for (const p of [[560,500],[900,430],[1250,520],[1580,470],[1200,640],[800,600]])
    await __demo.moveTo(p[0], p[1], 880);
  return 1;
})()
EOF
  hold 14500 '{x:420,y:300,w:1400,h:420}'
  stop_clip 06
}

shot07() { # Impact graph: the three buckets
  banner "shot 07 — three buckets (narration 17.9s)"
  prewarm "$APP/impact"
  start_clip 07
  js <<'EOF'
(async () => {
  const btns = [...document.querySelectorAll('button')];
  const pick = (re) => btns.find(b => re.test(b.textContent || ''));
  const patch = pick(/patch/i), unaff = pick(/unaffected/i), skip = pick(/skipped/i);
  await __demo.moveTo(300, 400, 700);
  if (patch) { await __demo.moveToEl(patch, 800); await __demo.sleep(1200); }
  await __demo.moveTo(900, 420, 900); await __demo.sleep(700);
  if (unaff) { await __demo.moveToEl(unaff, 900); await __demo.sleep(1200); }
  await __demo.moveTo(1000, 620, 900); await __demo.sleep(700);
  if (skip) { await __demo.moveToEl(skip, 900); await __demo.sleep(1200); }
  await __demo.moveTo(1150, 520, 900);
  return 1;
})()
EOF
  hold 21500 '{x:260,y:300,w:1300,h:420}'
  stop_clip 07
}

shot08() { # Impact graph: a skipped node's evidence
  banner "shot 08 — skipped node evidence (narration 16.6s)"
  prewarm "$APP/impact"
  start_clip 08
  js <<'EOF'
(async () => {
  await __demo.scrollBy(null, 430, 1100);
  await __demo.sleep(400);
  // Match the card's TITLE, not its text. Every skipped card quotes other models inside its
  // reason, so a plain textContent test opened mart_product_performance (whose reason cites
  // "`stg_order_items` columns") and put a model on screen that the narration does not describe.
  const card = [...document.querySelectorAll('button')].find(b => {
    const title = b.querySelector('span span');
    return title && title.textContent.trim() === 'stg_order_items';
  });
  if (card) await __demo.click(card, 1000);
  await __demo.sleep(1600);
  const drawer = document.querySelector('aside[class*="fixed"]');
  await __demo.moveTo(1560, 400, 900);
  if (drawer) await __demo.scrollBy(drawer, 240, 1400);
  await __demo.sleep(500);
  await __demo.moveTo(1600, 620, 900);
  if (drawer) await __demo.scrollBy(drawer, 200, 1300);
  return !!card;
})()
EOF
  hold 20500 '{x:1480,y:220,w:400,h:700}'
  stop_clip 08
}

shot09() { # Patches: the diff
  banner "shot 09 — patch diff (narration 17.6s)"
  prewarm "$APP/patches"
  start_clip 09
  js <<'EOF'
(async () => {
  await __demo.moveTo(640, 360, 700);
  const files = [...document.querySelectorAll('button')].filter(b => /\.(sql|py|yml)/.test(b.textContent || ''));
  if (files[1]) { await __demo.click(files[1], 900); await __demo.sleep(1200); }
  await __demo.moveTo(1300, 620, 900);
  await __demo.sleep(900);
  await __demo.moveTo(1180, 700, 800);
  await __demo.sleep(700);
  if (files[2]) { await __demo.click(files[2], 900); await __demo.sleep(1300); }
  await __demo.moveTo(1350, 640, 900);
  return files.length;
})()
EOF
  hold 21500 '{x:950,y:430,w:900,h:380}'
  stop_clip 09
}

shot10() { # Patches: validation evidence
  banner "shot 10 — validation 23/23 (narration 16.1s)"
  prewarm "$APP/patches"
  start_clip 10
  js <<'EOF'
(async () => {
  await __demo.moveTo(800, 500, 700);
  await __demo.scrollBy(null, 700, 1500);
  await __demo.sleep(600);
  await __demo.moveTo(560, 470, 900); await __demo.sleep(1000);
  await __demo.moveTo(900, 470, 800); await __demo.sleep(1000);
  await __demo.scrollBy(null, 220, 1200);
  await __demo.moveTo(900, 640, 900);
  return 1;
})()
EOF
  hold 20000 '{x:440,y:400,w:1200,h:380}'
  stop_clip 10
}

shot11() { # Pull request
  banner "shot 11 — pull request (narration 10.0s)"
  prewarm "$APP/pr"
  start_clip 11
  js <<'EOF'
(async () => {
  await __demo.moveTo(800, 400, 700);
  await __demo.scrollBy(null, 300, 1300);
  await __demo.moveTo(1100, 560, 900);
  await __demo.scrollBy(null, 320, 1300);
  return 1;
})()
EOF
  hold 13500 '{x:460,y:300,w:1200,h:460}'
  stop_clip 11
}

shot12() { # Write-back
  banner "shot 12 — write-back (narration 14.6s)"
  prewarm "$APP/writeback"
  start_clip 12
  js <<'EOF'
(async () => {
  await __demo.moveTo(760, 400, 700);
  await __demo.scrollBy(null, 240, 1200);
  await __demo.moveTo(1000, 520, 900); await __demo.sleep(600);
  await __demo.scrollBy(null, 280, 1300);
  await __demo.moveTo(820, 600, 900); await __demo.sleep(600);
  await __demo.scrollBy(null, 280, 1300);
  return 1;
})()
EOF
  hold 18500 '{x:440,y:300,w:1300,h:460}'
  stop_clip 12
}

shot13() { # DataHub again: the loop is closed
  banner "shot 13 — DataHub, repaired (narration 9.9s)"
  prewarm "$DH/dataset/$ORDERS_URN/Schema"
  start_clip 13
  js <<'EOF'
(async () => {
  await __demo.moveTo(400, 380, 700);
  await __demo.moveTo(560, 454, 900); await __demo.sleep(1100);
  await __demo.moveTo(1050, 454, 900); await __demo.sleep(800);
  await __demo.moveTo(900, 250, 900);
  return 1;
})()
EOF
  hold 13500 '{x:200,y:260,w:1000,h:340}'
  stop_clip 13
}

# ---------------------------------------------------------------- driver

ALL=(01 02 03 04 05 06 07 08 09 10 11 12 13)
WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=("${ALL[@]}")
want() { for w in "${WANT[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }

ab set viewport 1920 1080 >/dev/null
datahub_login

# A full pass drives the demo through its real state machine: clean -> drift -> run -> done.
# SKIP_RESET=1 when the catalog is already known clean — the re-seed takes ~4 minutes and
# blocks the API while it runs, so it is worth skipping on a retake.
if [ ${#WANT[@]} -eq ${#ALL[@]} ] && [ "${SKIP_RESET:-0}" != "1" ]; then
  reset_demo
fi

want 01 && shot01
want 02 && shot02
want 03 && shot03
if want 04 || want 05; then
  curl -s -m 30 "$API/api/drift" | grep -q 'dataset_urn' || apply_drift
fi
want 04 && shot04
want 05 && shot05
want 06 && shot06
want 07 && shot07
want 08 && shot08
want 09 && shot09
want 10 && shot10
want 11 && shot11
want 12 && shot12
want 13 && shot13

banner "capture complete"
for n in "${WANT[@]}"; do
  [ -f "$RAW/clip$n.webm" ] && printf '  clip%s  %ss\n' "$n" \
    "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$RAW/clip$n.webm")"
done
