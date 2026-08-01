import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  CircleDot,
  Clock3,
  GitPullRequest,
  Network,
  Play,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Split,
  TerminalSquare,
  TestTubeDiagonal,
  WandSparkles,
  Workflow,
  X,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../context/app-context'
import type { DriftEvent, RunEvent, RunPhase, Scenario } from '../lib/types'
import { cn, formatDuration, motionEase, referenceCounts } from '../lib/utils'
import { PageHeader } from '../components/page-header'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { EmptyState } from '../components/ui/empty-state'
import { LoadingPanel } from '../components/ui/skeleton'

const phaseDefinitions: Array<{ id: RunPhase; title: string; subtitle: string; icon: typeof ScanLine }> = [
  { id: 'detect', title: 'Detect schema drift', subtitle: 'Compare baseline with live DataHub schema', icon: ScanLine },
  { id: 'impact', title: 'Trace column lineage', subtitle: 'Classify the exact downstream blast radius', icon: Network },
  { id: 'codegen', title: 'Generate surgical patches', subtitle: 'Apply deterministic AST transformations', icon: WandSparkles },
  { id: 'validate', title: 'Validate every reference', subtitle: 'Resolve columns against catalog evidence', icon: TestTubeDiagonal },
  { id: 'pr', title: 'Package pull request', subtitle: 'Assemble review-ready lineage evidence', icon: GitPullRequest },
  { id: 'writeback', title: 'Write back to DataHub', subtitle: 'Persist lineage, governance, and audit state', icon: Workflow },
  { id: 'done', title: 'Repair complete', subtitle: 'Hand off a fully evidenced repair', icon: ShieldCheck },
]

const scenarioIcons = {
  RENAME: Split,
  RETYPE: RefreshCw,
  DROP: X,
}

function ToolChip({ event }: { event: RunEvent }) {
  const tool = typeof event.data.tool === 'string' ? event.data.tool : 'tool'
  const source = event.data.source === 'datahub_mcp' ? 'datahub' : 'repair_agent'
  const argument = tool === 'get_lineage'
    ? 'column="order_placed_at", max_hops=3'
    : tool === 'list_schema_fields'
      ? 'dataset="shop_prod.raw.orders"'
      : '…'
  return (
    <span className="inline-flex max-w-full items-center gap-2 rounded-[6px] border border-accent/30 bg-accent/[0.09] px-2.5 py-1.5 font-mono text-[10px] text-[#c7d2fe] shadow-[inset_0_1px_0_rgb(255_255_255/0.05)]">
      <TerminalSquare className="size-3 shrink-0 text-[#818cf8]" />
      <span className="truncate">{source}.{tool}({argument})</span>
    </span>
  )
}

function RunTimeline({
  events,
  status,
  completedStages,
  failedStage,
}: {
  events: RunEvent[]
  status: 'running' | 'succeeded' | 'failed'
  completedStages: string[]
  failedStage: string | null
}) {
  const [expanded, setExpanded] = useState<Set<RunPhase>>(new Set(['detect', 'impact']))
  const visibleEvents = events
    .filter((event) => event.level !== 'debug' || event.data.tool)
    .filter((event, index, filtered) => {
      if (index === 0) return true
      const previous = filtered[index - 1]
      return event.phase !== previous.phase
        || event.level !== previous.level
        || event.title !== previous.title
        || event.detail !== previous.detail
        || event.data.tool !== previous.data.tool
        || event.data.source !== previous.data.source
    })
  const lastPhase = visibleEvents.at(-1)?.phase
  const activeIndex = lastPhase ? phaseDefinitions.findIndex((phase) => phase.id === lastPhase) : -1
  const startedAt = events[0] ? new Date(events[0].ts).getTime() : Date.now()

  const toggle = (phase: RunPhase) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(phase)) next.delete(phase)
      else next.add(phase)
      return next
    })
  }

  return (
    <div className="relative">
      {phaseDefinitions.map((phase, index) => {
        const phaseEvents = visibleEvents.filter((event) => event.phase === phase.id)
        // Tick a phase only when the backend says it genuinely produced output. Inferring
        // completion from position meant a failed run showed green checks next to work that
        // never happened. 'done' has no artifact of its own, so it follows the run status.
        const completed = new Set(completedStages)
        const isDone =
          phase.id === 'done' ? status === 'succeeded' : completed.has(phase.id)
        const isFailed =
          status === 'failed' &&
          (failedStage ? phase.id === failedStage : index === activeIndex) &&
          !isDone
        const isActive = status === 'running' && index === activeIndex
        const hasActivity = phaseEvents.length > 0
        const first = phaseEvents[0] ? new Date(phaseEvents[0].ts).getTime() : startedAt
        const last = phaseEvents.at(-1) ? new Date(phaseEvents.at(-1)!.ts).getTime() : first
        const elapsed = Math.max(0, last - first)
        const Icon = phase.icon

        return (
          <motion.div
            key={phase.id}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: index * 0.03, ease: motionEase }}
            className="relative grid grid-cols-[32px_1fr] gap-3 pb-3 last:pb-0"
          >
            {index < phaseDefinitions.length - 1 && (
              <div className={cn('absolute left-[15px] top-7 h-[calc(100%-16px)] w-px', isDone ? 'bg-ok/35' : 'bg-border')} />
            )}
            <div className={cn(
              'relative z-10 flex size-8 items-center justify-center rounded-full border bg-surface transition-all duration-200',
              isDone && 'border-ok/45 bg-ok/10 text-[#6ee7b7]',
              isActive && 'border-accent/50 bg-accent/10 text-[#a5b4fc] shadow-[0_0_18px_rgb(99_102_241/0.2)]',
              isFailed && 'border-danger/50 bg-danger/10 text-[#fb7185]',
              !isDone && !isActive && !isFailed && 'border-border text-text-faint',
            )}>
              {isDone ? <Check className="size-3.5" /> : isActive ? <CircleDot className="size-3.5 animate-pulse" /> : <Icon className="size-3.5" />}
            </div>
            <div className={cn('min-w-0 rounded-[8px] border px-3 py-2.5', isActive ? 'border-accent/25 bg-accent/[0.045]' : 'border-transparent')}>
              <button className="flex w-full cursor-pointer items-center justify-between gap-4 border-0 bg-transparent p-0 text-left"
                type="button"
                onClick={() => toggle(phase.id)}
                disabled={!hasActivity}
              >
                <span className="min-w-0">
                  <span className={cn('block text-[12px] font-semibold', hasActivity || isActive || isDone ? 'text-text' : 'text-text-faint')}>{phase.title}</span>
                  <span className="block truncate text-[10px] text-text-faint">{phase.subtitle}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {hasActivity && <span className="font-mono text-[9px] text-text-faint">{formatDuration(elapsed)}</span>}
                  {hasActivity && <ChevronDown className={cn('size-3 text-text-faint transition-transform', expanded.has(phase.id) && 'rotate-180')} />}
                </span>
              </button>
              {expanded.has(phase.id) && phaseEvents.length > 0 && (
                <div className="mt-2 space-y-2 border-l border-border pl-3">
                  {phaseEvents.map((event) => (
                    <div key={event.seq} className="min-w-0">
                      {event.data.tool ? <ToolChip event={event} /> : (
                        <div>
                          <div className="text-[10px] font-medium text-text-dim">{event.title}</div>
                          {event.detail && <div className="mt-0.5 text-[10px] leading-4 text-text-faint">{event.detail}</div>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

export function ControlRoom() {
  const { currentRun, currentRunLoading, health, resetVersion, startRunState, streamConnected, streamError } = useApp()
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [drifts, setDrifts] = useState<DriftEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [busyScenario, setBusyScenario] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [useLlm, setUseLlm] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refreshDrift = async () => {
    const detected = await api.drift()
    setDrifts(detected)
    return detected
  }

  useEffect(() => {
    Promise.all([api.scenarios(), api.drift()])
      .then(([scenarioData, driftData]) => {
        setScenarios(scenarioData)
        setDrifts(driftData)
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Could not load the demo scenarios.'))
      .finally(() => setLoading(false))
  }, [resetVersion])

  useEffect(() => {
    if (health && !health.llm_available) setUseLlm(false)
  }, [health])

  const activeDrift = drifts[0] ?? currentRun?.drift ?? null
  const counts = useMemo(() => referenceCounts(currentRun), [currentRun])

  const applyScenario = async (scenario: Scenario) => {
    setBusyScenario(scenario.name)
    setError(null)
    try {
      await api.applyScenario(scenario.name)
      await refreshDrift()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not apply this drift scenario.')
    } finally {
      setBusyScenario(null)
    }
  }

  const runRepair = async () => {
    if (!activeDrift) return
    setRunning(true)
    setError(null)
    try {
      const result = await api.startRun({ drift_id: activeDrift.id, pr_mode: 'dry-run', use_llm: useLlm })
      startRunState(result.run_id, useLlm ? 'agent' : 'deterministic')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The repair run could not be started.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Live demo workspace"
        title="Control Room"
        detail="Introduce drift, watch the agent reason through DataHub, and inspect every repair artifact."
        actions={currentRun?.status === 'running' ? (
          <Badge variant={streamConnected ? 'ok' : 'patch'}>
            <span className={cn('size-1 rounded-full', streamConnected ? 'bg-ok' : 'bg-patch')} />
            {streamConnected ? 'SSE live' : 'reconnecting'}
          </Badge>
        ) : undefined}
      />

      {error && <div role="alert" className="mb-4 rounded-[8px] border border-danger/30 bg-danger/10 px-4 py-2.5 text-[11px] text-[#fda4af]">{error}</div>}
      {streamError && currentRun?.status === 'running' && <div className="mb-4 rounded-[8px] border border-patch/25 bg-patch/[0.06] px-4 py-2 text-[10px] text-[#fcd34d]">{streamError}</div>}

      {loading ? <div className="grid grid-cols-3 gap-3"><LoadingPanel rows={2} /><LoadingPanel rows={2} /><LoadingPanel rows={2} /></div> : (
        <section aria-labelledby="scenarios-title">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 id="scenarios-title" className="m-0 text-[13px] font-semibold text-text">Choose a controlled drift</h2>
              <p className="m-0 mt-0.5 text-[10px] text-text-faint">Each mutation is written to the live ShopFlow catalog.</p>
            </div>
            <Badge variant="neutral">3 supported drift types</Badge>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {scenarios.map((scenario, index) => {
              const Icon = scenarioIcons[scenario.kind]
              const isApplied = activeDrift?.id === scenario.drift_id
              return (
                <motion.div key={scenario.name} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: index * 0.03, ease: motionEase }}>
                  <Card className={cn('group h-full p-4 transition-all duration-200 hover:border-border-lit hover:bg-surface-2/50', isApplied && 'border-patch/35 bg-patch/[0.035]')}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex size-8 items-center justify-center rounded-[8px] border border-border-lit bg-surface-2 text-text-dim"><Icon className="size-4" /></div>
                      <Badge variant={isApplied ? 'patch' : 'neutral'}>{isApplied ? 'Live in catalog' : scenario.kind}</Badge>
                    </div>
                    <h3 className="mb-1 mt-4 text-[13px] font-semibold text-text">{scenario.title}</h3>
                    <p className="mb-4 mt-0 min-h-10 text-[10px] leading-[1.55] text-text-dim">{scenario.description}</p>
                    <Button variant={isApplied ? 'outline' : 'secondary'} size="sm" className="w-full" disabled={busyScenario !== null || isApplied} onClick={() => void applyScenario(scenario)}>
                      {busyScenario === scenario.name ? <RefreshCw className="size-3 animate-spin" /> : isApplied ? <Check className="size-3" /> : <Play className="size-3" />}
                      {busyScenario === scenario.name ? 'Applying to DataHub' : isApplied ? 'Drift applied' : 'Apply drift'}
                    </Button>
                  </Card>
                </motion.div>
              )
            })}
          </div>
        </section>
      )}

      {activeDrift && (
        <div className="mt-3 flex items-center gap-3 rounded-[9px] border border-patch/35 bg-patch/[0.075] px-4 py-3 text-[11px] text-[#fcd34d] shadow-[inset_3px_0_0_var(--patch)]">
          <CircleDot className="size-4 shrink-0 text-patch" />
          <span className="min-w-0 flex-1">
            Upstream drift live in DataHub: <code className="text-[#fde68a]">{activeDrift.dataset_name}.{activeDrift.old_column}</code>
            {activeDrift.new_column ? <> <ArrowRight className="mx-1 inline size-3" /> <code className="text-[#fde68a]">{activeDrift.new_column}</code></> : ' was dropped'}.
          </span>
          <Badge variant="patch">{Math.round(activeDrift.confidence * 100)}% confidence</Badge>
        </div>
      )}

      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_390px] gap-4">
        <section className="min-w-0">
          <Card className="relative overflow-hidden border-accent/25 bg-[linear-gradient(135deg,rgb(99_102_241/0.09),transparent_48%)] p-5">
            <div className="pointer-events-none absolute -right-16 -top-20 size-56 rounded-full bg-accent/[0.08] blur-3xl" />
            <div className="relative flex items-end justify-between gap-6">
              <div>
                <Badge variant="accent"><Sparkles className="size-3" /> Evidence-first repair</Badge>
                <h2 className="mb-1 mt-3 text-[18px] font-semibold text-text">Turn drift into a validated change set</h2>
                <p className="m-0 max-w-xl text-[11px] leading-5 text-text-dim">The agent reads column lineage through DataHub MCP, changes code deterministically, and blocks every unresolvable reference before review.</p>
              </div>
              <div className="shrink-0 space-y-2">
                <div className="flex rounded-[8px] border border-border bg-bg/70 p-1">
                  <Button size="sm" variant={useLlm ? 'secondary' : 'ghost'} className="h-7" disabled={!health?.llm_available} onClick={() => setUseLlm(true)}><WandSparkles className="size-3" />Agent + MCP</Button>
                  <Button size="sm" variant={!useLlm ? 'secondary' : 'ghost'} className="h-7" onClick={() => setUseLlm(false)}>Deterministic</Button>
                </div>
                <Button
                  size="lg"
                  variant="primary"
                  className="group w-full min-w-52 overflow-hidden"
                  disabled={!activeDrift || running || currentRun?.status === 'running'}
                  onClick={() => void runRepair()}
                >
                  <span className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-transparent via-white/15 to-transparent opacity-0 group-hover:opacity-100 group-hover:[animation:sheen_1.1s_ease-in-out]" />
                  {running ? <RefreshCw className="size-4 animate-spin" /> : <Play className="size-4 fill-current" />}
                  {currentRun?.status === 'running' ? 'Repair agent running' : running ? 'Starting repair' : 'Run repair agent'}
                </Button>
              </div>
            </div>
          </Card>

          {currentRun?.status === 'failed' && (
            <div className="mt-3 rounded-[10px] border border-danger/40 bg-danger/[0.07] px-4 py-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="size-3.5 shrink-0 text-danger" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-danger">
                  Repair run failed{currentRun.failed_stage ? ` at the ${currentRun.failed_stage} stage` : ''}
                </span>
              </div>
              <p className="m-0 mt-1.5 text-[11px] leading-5 text-text-dim">
                {currentRun.error ?? 'The run did not complete. Inspect the timeline below for the failing stage.'}
              </p>
              <p className="m-0 mt-1.5 text-[10px] leading-4 text-text-faint">
                The figures below describe an incomplete run and must not be read as a clean bill of health.
              </p>
            </div>
          )}

          {currentRun?.status === 'succeeded' && currentRun.pr?.state === 'no_changes_required' && (
            <div className="mt-3 rounded-[10px] border border-ok/35 bg-ok/[0.07] px-4 py-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-3.5 shrink-0 text-ok" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ok">No code changes required</span>
              </div>
              <p className="m-0 mt-1.5 text-[11px] leading-5 text-text-dim">
                DataHub and the catalog agree that no mapped code references the changed column,
                so this repair had nothing to patch and no pull request was opened. A previous run
                may already have repaired it.
              </p>
            </div>
          )}

          {currentRun?.impact && (
            <div className="mt-3 grid grid-cols-4 gap-2">
              <SummaryCard label="Require patch" value={currentRun.impact.stats.requires_patch ?? 0} color="patch" />
              <SummaryCard label="No code change" value={currentRun.impact.stats.downstream_unaffected ?? 0} color="unaffected" />
              {/* Only claim the skips were CORRECT when the run actually succeeded. */}
              <SummaryCard
                label={currentRun.status === 'succeeded' ? 'Correctly skipped' : 'Skipped (unverified)'}
                value={currentRun.impact.stats.skipped ?? 0}
                color="skipped"
              />
              <SummaryCard label="References validated" value={`${counts.resolved}/${counts.total}`} color="ok" />
            </div>
          )}
        </section>

        <Card className="min-h-[410px] p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="m-0 text-[13px] font-semibold text-text">Live execution</h2>
              <p className="m-0 mt-0.5 text-[10px] text-text-faint">Seven gated phases, streamed as they happen.</p>
            </div>
            {currentRun && <Badge variant={currentRun.status === 'succeeded' ? 'ok' : currentRun.status === 'failed' ? 'danger' : 'accent'}>{currentRun.events.length} events</Badge>}
          </div>
          {currentRunLoading ? <LoadingPanel rows={5} className="border-0 bg-transparent p-0 shadow-none" /> : currentRun ? (
            <RunTimeline events={currentRun.events} status={currentRun.status} completedStages={currentRun.completed_stages ?? []} failedStage={currentRun.failed_stage ?? null} />
          ) : (
            <EmptyState icon={Clock3} title="Waiting for a repair run" detail="Apply a drift scenario, then start the agent to see DataHub MCP calls and validation gates here." className="min-h-[330px] border-0 bg-transparent" />
          )}
        </Card>
      </div>
    </div>
  )
}

function SummaryCard({ label, value, color }: { label: string; value: string | number; color: 'patch' | 'unaffected' | 'skipped' | 'ok' }) {
  const colorClasses = { patch: 'text-patch', unaffected: 'text-unaffected', skipped: 'text-[#94a3b8]', ok: 'text-ok' }
  return (
    <Card className="px-3 py-2.5 shadow-none">
      <div className={cn('font-mono text-[17px] font-semibold leading-none', colorClasses[color])}>{value}</div>
      <div className="mt-1.5 text-[9px] font-medium uppercase tracking-[0.08em] text-text-faint">{label}</div>
    </Card>
  )
}
