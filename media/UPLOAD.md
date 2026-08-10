# Upload-ready video metadata

**File:** `media/schema-drift-auto-repair-agent.mp4` — 1920×1080, H.264/AAC, **2:54** (174.009 s), 15,818,113 bytes
**Captions:** `media/schema-drift-auto-repair-agent.srt` — 59 cues, worded from the script, timed by Deepgram word alignment
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
Someone upstream renames one column. Nothing crashes. The queries below it keep running,
quietly returning wrong numbers, and nobody notices for days.

This agent closes that loop, and the video walks the machinery in order: what DataHub
provides, how the agent uses each capability at the moment it uses it, and what the run
actually produced.

Four DataHub capabilities do the work, each named on screen as it is used:

1. Schema metadata — the live schema for the drifted table is read from DataHub and compared
   with the committed baseline. order_placed_at is gone; order_created_at is present with the
   same type at the same ordinal position, so the change is inferred as a rename.
2. Column-level lineage — the capability that makes the whole thing possible. DataHub records
   which downstream COLUMN each column feeds, so the agent can ask what reads this column
   rather than what touches this table. That is what turns two answers into three.
3. Incidents API — the repair is filed as an OSS incident entity, moved to TRIAGE.
4. Catalog write-back — corrected fine-grained lineage, column documentation, tags, an
   institutional-memory link and a process-instance record, all written into the catalog where
   the next engineer looks.

Reads go through the DataHub MCP server (search, list_schema_fields, get_lineage on the changed
column, get_dataset_queries, get_lineage_paths_between). Writes go through the DataHub Python
SDK. In the run shown here: 8 DataHub MCP calls and 6 repair-stage tool calls, 14 in total.

What column-level lineage buys you, in this run: three files genuinely read the changed column
and need patching; two marts sit downstream but read order_date — a copy renamed one hop
further up, visible on screen as a CAST_DATE edge — so they need nothing at all; and seven
models are correctly left alone, each with a stated reason you can open and read. Anyone can
list everything downstream of a table. Knowing what genuinely breaks is the hard part.

The language model never writes the code. sqlglot locates the references and rewrites the
syntax tree, so only the changed tokens move and the diff is one a human will actually review.
Every column reference is then resolved before the pull request can open — 23 of 23 in this
run — and a single unresolvable reference blocks the whole patch. The gate is enforced, not
advisory.

Built for "Build with DataHub: The Agent Hackathon" — Metadata-Aware Code Generation &
Development track.

Chapters
0:00  The problem: schema drift
0:12  What DataHub provides
0:27  Breaking it on purpose
0:40  Capability 1 — schema metadata
0:51  The agent's MCP calls
1:09  Capability 2 — column-level lineage
1:21  Three answers, not two
1:37  Why a model was skipped
1:51  Deterministic patches
2:02  The validation gate
2:17  The pull request
2:26  Capabilities 3 and 4 — write-back
2:41  What makes it work

Code, setup instructions and generated example artifacts:
https://github.com/yadneshSalvi/datahub-repair-agent

Apache 2.0. Runs against a local DataHub Core quickstart — no DataHub Cloud required.

Note on honesty, since the video states numbers. Every figure comes from one run,
run-8cfa00cde7b348109b90ece8ed027904, which is the only run id visible anywhere in the cut.
"23 of 23" breaks down on screen as 15 references resolved against live DataHub schemas, 6
against the projected post-repair schema of models patched earlier in the same run, and 2
locally derived CTE outputs; the narration states that breakdown aloud. DataHub Cloud's
metadata change proposals do not exist in OSS, so the governance write-back uses the OSS
incident entity plus a dry-run review gate rather than claiming a feature we don't have.

About the split-screen technical panels. The call list, the schema fact and the column-lineage
chain shown beside the footage are rendered from that run's own persisted record — tool names,
their order and their wall-clock timestamps are verbatim from the run log, and the lineage
chain (IDENTITY → CAST_DATE → IDENTITY) is verbatim from the recorded lineage edges. The agent
runs with SDK tracing disabled, so the raw MCP request and response payloads were never
persisted; rather than reconstruct them, every argument value the run did not record is shown
as an ellipsis, and the panel says so on screen: "tool arguments were not logged, results
abbreviated".

One editing note: the agent's actual run takes about three and a half minutes, and the section
showing it working is played at roughly 3.4x so it fits the narration. Every tool call you see
land really landed, in that order, in that run — only the waiting between them was shortened.
Nothing else in the video is sped up.

Relatedly, the age chips visible on some screens ("started 25m ago", "1.0.0 · 34 minutes ago")
are simply because the result screens were filmed a few minutes after the live run finished.
They refer to the same run you watched start.
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
   "a real write to real DataHub" being heard as "a real right", and "nothing here is mocked"
   as "nothing here is marked" — both reworded rather than shipped.
4. `media/capture.sh` — drives agent-browser through 13 shots into `media/raw/clipNN.webm`.
   `capture.sh 08` re-shoots a single shot. `SETTLE=8 capture.sh 13` for pages that paint slowly.
   **This cut did not re-capture anything**: it re-narrates and re-frames the same masters.
5. `media/panels/render.py` — renders each split-screen panel state and each feature chip to PNG
   with headless Chrome, at 2x, using the web app's own fonts and colour tokens.
6. `media/assemble.py` — trims each clip's settle window, applies the camera treatment or the
   split-screen composition, cuts panel reveals to word timestamps, concatenates, tempo-fits the
   narration to under 3:00, muxes. Hard-errors if the finished file reaches 3:00.
7. `media/subtitles.py` — SRT worded from `narration.txt`, timed by Deepgram word alignment
   (`media/align.py`), checked against the video length.
8. `media/qa_video.py` — gates duration, static stretches, black frames and loading frames.
   `media/contact_sheet.sh` renders a sheet for eyeballing.

### Things that will bite you if you re-cut this

- **Playwright's video pipeline ignores CSS `zoom`** on both `<html>` and `<body>`. A
  screenshot shows the zoom; the recorded frame does not. Close-ups are therefore made by
  cropping real pixels in `assemble.py`, not by zooming the browser.
- **ffmpeg's crop is `w:h:x:y`**, not `x:y:w:h`. Getting it backwards yields a tiny sliver from
  the wrong corner, which reads as a black frame with a thin bar.
- **A still image overlaid without `-loop 1` is a single frame at t=0.** With a `fade=t=in`
  on it, that frame is rendered at alpha 0 and `overlay` then repeats it forever — the graphic
  never appears, and nothing errors. Both feature chips were invisible until this was fixed.
- **`align.normalise` folds spelt-out numbers to digits** so the aligner can match "twenty
  three" to "23". Reusing it to match caption phrases silently breaks them, because the phrase
  table is written in words. Caption matching uses its own punctuation-only key.
- **`agent-browser eval` must not block for long** — a single 84-second call returns
  `Resource temporarily unavailable (os error 35)`. Long holds are chunked.
- **Run the agent with a healthy uv cache.** A damaged one makes `uvx mcp-server-datahub` fail,
  and the agent then degrades silently to deterministic mode with zero MCP tool calls — the run
  still succeeds, so the only symptom is that the tool chips never appear.

### Evidence lockstep — every claim, and where it comes from

All from `run-8cfa00cde7b348109b90ece8ed027904`, verified against the persisted run record:

| Claim | Source |
|---|---|
| 3 require patch / 2 unaffected / 7 skipped, 12 scanned, 3 hops | `impact.stats` |
| 4 patched files | `events[30].data.files` |
| 23 of 23 references — 15 live catalog, 6 projected repair, 2 local CTE | `patches[].references[].source` |
| 6 write-backs, all succeeded | `writeback[]` |
| 8 DataHub MCP calls, 6 repair-stage calls, 14 total | `events[]` where `data.source` is set |
| IDENTITY → CAST_DATE → IDENTITY column chain | `impact.graph.edges` |
| incident `urn:li:incident:fc3a618c…`, ACTIVE / TRIAGE | `events[45]`, `writeback[3]` |

The MCP call count is deliberately never spoken: it varies between runs, and a spoken number
that a re-run would contradict is exactly what the honest-claims rule exists to prevent.

### Constraints enforced while recording

- Agent + MCP mode, verified `degraded: false` on the filmed run, so the MCP chips are real
- Demo reset before the take — a second run over already-repaired code correctly narrows to
  fewer patches, so an un-reset retake would show smaller numbers than the narration states
- The **Run repair agent** button is genuinely clicked on camera; the run on screen is the run
  every later number is read from
- The catalog is left pristine after filming, so a judge who clones the repo starts where the
  video starts
