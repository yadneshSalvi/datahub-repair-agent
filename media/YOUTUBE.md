# YouTube upload: copy-paste pack

**Video file:** `schema-drift-auto-repair-agent.mp4` · **Captions:** upload
`schema-drift-auto-repair-agent.srt` (English) ·
**Thumbnail:** `schema-drift-auto-repair-agent-thumbnail.png` (1280x720) · **Visibility:** Public

## Title (83 characters, limit is 100)

```
Schema-Drift Auto-Repair Agent: column-level lineage that fixes the code it breaks
```

## Description

```
Someone upstream renames one column. Nothing crashes. The queries below it keep running, quietly returning wrong numbers, and nobody notices for days. This agent closes that loop: it finds exactly what breaks using DataHub's column-level lineage, repairs the code deterministically, and ships the fix as a pull request a human can review.

Code, setup instructions and generated example artifacts: https://github.com/yadneshSalvi/datahub-repair-agent

Built for "Build with DataHub: The Agent Hackathon", Metadata-Aware Code Generation track. The video walks the machinery in order: what DataHub provides, how the agent uses each capability at the moment it uses it, and what the run actually produced.

Four DataHub capabilities do the work, each named on screen as it is used:
1. Schema metadata. The live schema is read from DataHub and compared with the committed baseline; same type, same position, new name, so the change is inferred as a rename.
2. Column-level lineage, the one that matters. DataHub records which downstream column each column feeds, so the agent asks what reads this column rather than what touches this table. In this run that turns two answers into three: 3 assets genuinely read the changed column and get patched (4 files across them), 2 marts are downstream but insulated by an alias created one hop up and need nothing, and 7 models are correctly skipped, each with a stated reason.
3. Incidents API. The repair is filed as an OSS incident and moved to triage.
4. Catalog write-back. Corrected fine-grained lineage, column documentation, tags, an institutional-memory link and a process-instance run record all go back into the catalog where the next engineer looks.

Reads go through the DataHub MCP server (search, list_schema_fields, get_lineage on the changed column, get_dataset_queries, get_lineage_paths_between). Writes go through the DataHub Python SDK. The run shown makes 14 tool calls, 8 of them DataHub MCP reads, all visible live in the UI timeline.

The language model never writes the code. sqlglot locates the references and edits the syntax tree, so only the changed tokens move. Every column reference is then resolved against the live catalog before the pull request can open (23 of 23 in this run), and a single unresolvable reference blocks the whole patch.

Chapters
0:00 The problem: schema drift
0:12 What DataHub provides
0:27 Breaking it on purpose
0:40 Capability 1: schema metadata
0:51 The agent's MCP calls
1:09 Capability 2: column-level lineage
1:21 Three answers, not two
1:37 Why a model was skipped
1:51 Deterministic patches
2:02 The validation gate
2:17 The pull request
2:26 Capabilities 3 and 4: write-back
2:41 What makes it work

Apache 2.0, reproducible with one clone against a stock datahub docker quickstart. No Snowflake account needed.

#DataHub #DataEngineering #AIAgents #MCP #DataLineage #dbt
```

## Tags (video tags field)

```
datahub, data engineering, schema drift, data lineage, column-level lineage, ai agents, llm, mcp, model context protocol, sqlglot, dbt, airflow, code generation, data catalog
```

## After upload

1. Confirm visibility is Public and captions are attached.
2. Paste the URL into README.md (replace the "A YouTube link will replace this" line in the Demo section).
3. Paste the URL into the Devpost form (see `plans/09b_devpost_submission_final.md`).
