// Source of truth: src/repair_agent/models.py. Keep these interfaces in lockstep with Pydantic.

export type DriftKind = 'RENAME' | 'RETYPE' | 'DROP' | 'ADD'
export type ImpactBucket = 'REQUIRES_PATCH' | 'DOWNSTREAM_UNAFFECTED' | 'SKIPPED'
export type RunStatus = 'running' | 'succeeded' | 'failed'
export type RunPhase = 'detect' | 'impact' | 'codegen' | 'validate' | 'pr' | 'writeback' | 'done'

export interface ColumnSpec {
  name: string
  native_type: string
  data_type: string
  description: string | null
  nullable: boolean
}

export interface DatasetSchema {
  dataset_urn: string
  columns: ColumnSpec[]
}

export interface DriftEvent {
  id: string
  kind: DriftKind
  dataset_urn: string
  dataset_name: string
  old_column: string | null
  new_column: string | null
  old_type: string | null
  new_type: string | null
  confidence: number
  rationale: string
  detected_at: string
}

export interface LineageHop {
  upstream_urn: string
  upstream_column: string | null
  downstream_urn: string
  downstream_column: string | null
  transform_operation: string | null
  hops: number | null
}

export interface LineageNode {
  urn: string
  name: string
  kind: string
  bucket: ImpactBucket | null
  columns: string[]
  hops: number | null
  datahub_url: string | null
}

export interface LineageEdge {
  source_urn: string
  target_urn: string
  source_columns: string[]
  target_columns: string[]
  transform_operation: string | null
}

export interface LineageGraph {
  nodes: LineageNode[]
  edges: LineageEdge[]
}

export interface ImpactedAsset {
  urn: string
  name: string
  kind: string
  bucket: ImpactBucket
  hops: number | null
  matched_columns: string[]
  code_path: string | null
  reason: string
  lineage_path: LineageHop[]
  captured_queries: string[]
}

export interface ImpactReport {
  drift: DriftEvent
  assets: ImpactedAsset[]
  graph: LineageGraph
  stats: Record<string, number>
}

export type ReferenceStatus = 'OK' | 'UNKNOWN_COLUMN' | 'UNKNOWN_TABLE' | 'STALE_OLD_NAME'
export type ReferenceSource = 'live_catalog' | 'projected_repair' | 'local_cte' | 'unresolved'

export interface ReferenceCheck {
  table: string
  column: string
  line: number | null
  status: ReferenceStatus
  detail: string
  source: ReferenceSource
}

export type PatchKind = 'dbt_sql' | 'dbt_schema_yml' | 'airflow_python' | 'dbt_test'

export interface Patch {
  asset_urn: string
  file_path: string
  before: string
  after: string
  unified_diff: string
  kind: PatchKind
  references: ReferenceCheck[]
  valid: boolean
  strategy: string
}

export interface FileChange {
  path: string
  content: string
  previous_content: string | null
}

export interface PullRequestResult {
  mode: 'live' | 'dry-run'
  url: string
  branch: string
  title: string | null
  number: number | null
  files: string[]
  ok: boolean
  error: string | null
  /** 'no_changes_required' is a success — never style it as a failure. */
  state: 'opened' | 'no_changes_required' | 'blocked'
}

export interface WritebackAction {
  kind: string
  target_urn: string
  detail: string
  datahub_url: string
  ok: boolean
  error: string | null
}

export interface RunEvent {
  seq: number
  ts: string
  phase: RunPhase
  level: 'debug' | 'info' | 'warning' | 'error'
  title: string
  detail: string
  data: Record<string, unknown>
}

export interface RepairRun {
  id: string
  status: RunStatus
  /** Populated whenever status is 'failed' — never render a failed run as a success. */
  error: string | null
  failed_stage: string | null
  /** Phases that genuinely produced output; drives the timeline ticks. */
  completed_stages: string[]
  mode: 'agent' | 'deterministic'
  degraded: boolean
  degradations: string[]
  drift: DriftEvent | null
  impact: ImpactReport | null
  patches: Patch[]
  pr: PullRequestResult | null
  writeback: WritebackAction[]
  events: RunEvent[]
  started_at: string
  finished_at: string | null
}

export interface HealthResponse {
  ok: boolean
  datahub_reachable: boolean
  gms_url: string
  llm_available: boolean
  degradations: string[]
}

export interface Scenario {
  name: string
  drift_id: string
  kind: Exclude<DriftKind, 'ADD'>
  title: string
  description: string
}

export interface CatalogDataset {
  urn: string
  name: string
  subtypes: string[]
  schema: DatasetSchema
}

export interface StartRunRequest {
  drift_id: string
  pr_mode: 'dry-run' | 'live'
  use_llm: boolean
}
