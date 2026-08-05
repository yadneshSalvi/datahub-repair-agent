# Upload-ready video metadata

**File:** `media/schema-drift-auto-repair-agent.mp4` — 1920×1080, H.264/AAC, **2:51**, 26.5 MB
**Captions:** `media/schema-drift-auto-repair-agent.srt` — 55 cues, Deepgram word-level timing
**Visibility:** Public (Devpost requires a publicly viewable video under 3 minutes)

---

## Title

```
Schema-Drift Auto-Repair Agent — column-level lineage that fixes the code it breaks
```

Alternate, if a shorter title is wanted:
```
Schema-Drift Auto-Repair Agent | Built with DataHub
```

---

## Description

```
Someone upstream renames one column. Nothing crashes. The pipelines below keep running,
quietly producing wrong numbers, and nobody notices for days.

This agent closes that loop. It detects the drift, uses DataHub's column-level lineage to work
out the real blast radius, rewrites the affected dbt SQL, schema.yml and Airflow DAG code with
sqlglot syntax-tree edits, checks every column reference against the catalog before anything
ships, opens a pull request carrying the lineage evidence, and writes the repair back into
DataHub.

What's different here: column-level lineage gives three answers, not two. In this run, three
files genuinely read the changed column and need fixing; two marts sit downstream but read a
renamed copy made further upstream, so they need nothing at all; and seven models are
correctly left alone — each with a stated reason you can open and read. Anyone can list
everything downstream of a table. Knowing what genuinely breaks is the hard part.

The language model never writes the code. sqlglot locates the references and only the changed
tokens move, so the diff is one a human will actually review. Every column reference is then
resolved before the pull request can open — 23 of 23 in this run — and a single unresolvable
reference blocks the whole patch. The gate is enforced, not advisory.

Built for "Build with DataHub: The Agent Hackathon" — Metadata-Aware Code Generation &
Development track.

DataHub is used on both sides. Reads go through the DataHub MCP server (search,
list_schema_fields, get_lineage on the changed column, get_dataset_queries,
get_lineage_paths_between — 9 DataHub MCP calls out of 15 total tool calls in the run you see
here). Writes go through the DataHub Python SDK: fine-grained lineage, column documentation,
tags, an incident, an institutional-memory link, and a process-instance record.

Chapters
0:00  What DataHub is
0:12  The silent failure
0:24  Break it on purpose
0:36  The detector's evidence
0:45  The agent reads DataHub through MCP
1:06  Column-level lineage
1:16  Three answers, not two
1:32  Why a model was skipped
1:48  Surgical patches
2:04  The validation gate
2:19  The pull request
2:28  Writing the repair back
2:41  What makes it work

Code, setup instructions and generated example artifacts:
https://github.com/yadneshSalvi/datahub-repair-agent

Apache 2.0. Runs against a local DataHub Core quickstart — no DataHub Cloud required.

Note on honesty, since the video states numbers: the "23 of 23" figure breaks down on screen
as 15 references resolved against live DataHub schemas, 6 against the projected post-repair
schema of models patched earlier in the same run, and 2 locally derived CTE outputs. DataHub
Cloud's metadata change proposals do not exist in OSS, so the governance write-back uses the
OSS incident entity plus a dry-run review gate rather than claiming a feature we don't have.
```

---

## Tags

```
DataHub, data engineering, data lineage, column-level lineage, dbt, Airflow, schema drift,
AI agent, MCP, Model Context Protocol, sqlglot, metadata, data catalog, hackathon
```

---

## Reproducing this cut

Everything is scripted; nothing is hand-edited.

1. `make demo` — backend :8002, UI :3002 (DataHub quickstart GMS must be on :8081)
2. `media/tts.py` — Gemini TTS (`gemini-2.5-pro-preview-tts`, voice Charon), one WAV per
   narration paragraph into `media/raw/`. `media/tts.py 9 12` re-cuts only those paragraphs.
3. `media/verify_tts.py` — **transcribes every WAV back with Deepgram and diffs it against the
   script.** Non-zero exit if any word is mangled. This is not optional: it is what caught
   "lineage to find" being read as "lineage to define" and "one file before" as "one filed
   before", both of which would otherwise have shipped.
4. `media/capture.sh` — drives agent-browser through 13 shots into `media/raw/clipNN.webm`.
   `capture.sh 08` re-shoots a single shot. `SETTLE=8 capture.sh 13` for pages that paint slowly.
5. `media/assemble.sh` — trims each clip's settle window, applies the per-shot crop, camera pan
   and speed ramp, concatenates, tempo-fits the narration to ≤3:00, muxes.
6. `media/subtitles.py` — Deepgram `nova-2` word timestamps → SRT, checked against the video length.
7. `media/qa_video.py` — gates duration, static stretches, black frames and loading frames.
   `media/contact_sheet.sh` renders a sheet for eyeballing.

### Things that will bite you if you re-cut this

- **Playwright's video pipeline ignores CSS `zoom`** on both `<html>` and `<body>`. A
  screenshot shows the zoom; the recorded frame does not. Close-ups are therefore made by
  cropping real pixels in `assemble.sh`, not by zooming the browser.
- **ffmpeg's crop is `w:h:x:y`**, not `x:y:w:h`. Getting it backwards yields a tiny sliver from
  the wrong corner, which reads as a black frame with a thin bar.
- **`agent-browser eval` must not block for long** — a single 84-second call returns
  `Resource temporarily unavailable (os error 35)`. Long holds are chunked.
- **Most screens do not scroll at the window level** at 1080p; the long content lives in inner
  `overflow:auto` containers, and `/impact` and `/writeback` have no scroller at all. That is
  why each shot carries a slow camera pan — otherwise those shots are motionless.
- **Run the agent with a healthy uv cache.** A damaged one makes `uvx mcp-server-datahub` fail,
  and the agent then degrades silently to deterministic mode with zero MCP tool calls — the run
  still succeeds, so the only symptom is that the tool chips never appear.

### Constraints enforced while recording

- Agent + MCP mode, verified `degraded: false` on the filmed run, so the MCP chips are real
- Demo reset before the take — a second run over already-repaired code correctly narrows to
  fewer patches, so an un-reset retake would show smaller numbers than the narration states
- Every spoken number checked against the filmed run: 3 / 2 / 7, 4 patches, 23/23 references
  (15 live catalog, 6 projected repair, 2 local CTE), 6 write-backs, 15 tool calls
- The **Run repair agent** button is genuinely clicked on camera; the run on screen is the run
  every later number is read from
