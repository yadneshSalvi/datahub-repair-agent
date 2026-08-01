# Upload-ready video metadata

**File:** `media/schema-drift-auto-repair-agent.mp4` — 1280×720, H.264/AAC, **2:29**, 5.3 MB
**Captions:** `media/schema-drift-auto-repair-agent.srt` — 37 cues, Deepgram word-level timing
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
An upstream column gets renamed. Nothing errors. Downstream models keep running and quietly
produce wrong numbers — and you find out days later from someone looking at a bad dashboard.

This agent closes that loop. It detects the drift, uses DataHub's column-level lineage to
compute the real blast radius, rewrites the affected dbt SQL, schema.yml and Airflow DAG code
with sqlglot AST edits, validates every column reference against the catalog before anything
ships, opens a pull request carrying the lineage evidence, and writes the repair back into
DataHub.

What's different here: column-level lineage gives three answers, not two. In this demo, three
files genuinely reference the changed column and need a patch; two marts sit inside the blast
radius but read an alias created upstream, so they need no change at all; and seven models are
correctly skipped — each with a stated reason. Knowing what genuinely breaks is the hard part.

The language model never writes code. sqlglot locates the references and only the changed
tokens move, so the diff is one a human will actually review. Every column reference is then
resolved before the pull request can open — 23 of 23 in this run, and a single unresolvable
reference blocks the whole patch. The gate is enforced, not advisory.

Built for "Build with DataHub: The Agent Hackathon" — Metadata-Aware Code Generation &
Development track.

DataHub is used on both sides: reads go through the DataHub MCP server (search,
list_schema_fields, get_lineage on the changed column, get_dataset_queries,
get_lineage_paths_between — 13 tool calls in the run you see here), and writes go through the
DataHub Python SDK (fine-grained lineage, column documentation, tags, an incident, an
institutional-memory link, and a process-instance record).

Chapters
0:00  The problem
0:14  Introducing the drift
0:27  The agent reads DataHub through MCP
0:48  Three answers, not two
1:09  Why a model was skipped
1:26  Surgical patches
1:39  The validation gate
1:55  The pull request
2:06  Writing the repair back
2:19  Architecture

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

## Production notes (for re-cuts)

Everything is reproducible from the repo:

1. `make demo` — backend :8002, UI :3002
2. `media/tts.py` — Gemini TTS (`gemini-2.5-pro-preview-tts`, voice Charon), one WAV per
   narration paragraph, written to `media/raw/`
3. Screen capture via `agent-browser record` at 1280×720 into `media/raw/clipNN.webm`
4. `media/assemble.sh` — fits each clip to its narration segment (takes the clip's TAIL, so
   page-load and layout shift are cut), concatenates, muxes to MP4
5. `media/subtitles.py` — Deepgram `nova-2` word timestamps → SRT

Constraints that were enforced while recording:
- Agent + MCP mode, so the MCP tool-call chips appear live
- MCP server pre-warmed (a cold `uvx` start is ~90 s)
- DataHub logged in and its onboarding tooltip dismissed beforehand
- Demo reset between takes — a second run correctly narrows to fewer patches, so an un-reset
  retake would show smaller numbers than the narration states
- Every spoken number was checked against the recorded run: 3/2/7, 4 patches, 23/23
  references, 6/6 write-backs, 13 MCP tool calls
