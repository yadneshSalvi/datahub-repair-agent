import { ArrowRight, Braces, Check, Database, GitCompareArrows, ScanSearch } from 'lucide-react'
import { motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../context/app-context'
import type { CatalogDataset, ColumnSpec, DriftEvent } from '../lib/types'
import { cn, motionEase } from '../lib/utils'
import { PageHeader } from '../components/page-header'
import { Badge } from '../components/ui/badge'
import { Card } from '../components/ui/card'
import { EmptyState } from '../components/ui/empty-state'
import { LoadingPanel } from '../components/ui/skeleton'

interface ColumnPair {
  before: ColumnSpec | null
  after: ColumnSpec | null
  changed: boolean
}

function pairColumns(dataset: CatalogDataset, drift: DriftEvent): ColumnPair[] {
  const live = dataset.schema.columns
  if (drift.kind === 'RENAME') {
    return live.map((column) => column.name === drift.new_column
      ? { before: { ...column, name: drift.old_column ?? column.name, native_type: drift.old_type ?? column.native_type }, after: column, changed: true }
      : { before: column, after: column, changed: false })
  }
  if (drift.kind === 'RETYPE') {
    return live.map((column) => column.name === drift.old_column
      ? { before: { ...column, native_type: drift.old_type ?? column.native_type }, after: { ...column, native_type: drift.new_type ?? column.native_type }, changed: true }
      : { before: column, after: column, changed: false })
  }
  if (drift.kind === 'DROP') {
    const removed: ColumnSpec = { name: drift.old_column ?? 'removed_column', native_type: drift.old_type ?? 'UNKNOWN', data_type: 'unknown', description: null, nullable: true }
    return [...live.map((column) => ({ before: column, after: column, changed: false })), { before: removed, after: null, changed: true }]
  }
  return live.map((column) => ({ before: column, after: column, changed: false }))
}

function ColumnRow({ column, changed, side, kind }: { column: ColumnSpec | null; changed: boolean; side: 'before' | 'after'; kind: DriftEvent['kind'] }) {
  return (
    <div className={cn(
      'flex h-[54px] items-center justify-between gap-3 border-b border-border/70 px-4 last:border-0',
      changed ? side === 'before' ? 'bg-danger/[0.055]' : 'bg-ok/[0.055]' : 'opacity-55',
    )}>
      {column ? (
        <>
          <div className="min-w-0">
            <div className={cn('truncate font-mono text-[10px] font-medium', changed ? side === 'before' ? 'text-[#fda4af]' : 'text-[#a7f3d0]' : 'text-text')}>{column.name}</div>
            <div className="mt-0.5 truncate text-[9px] text-text-faint">{column.description ?? (column.nullable ? 'Nullable field' : 'Required field')}</div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!column.nullable && <span className="text-[7px] font-semibold uppercase tracking-[0.1em] text-text-faint">required</span>}
            <span className={cn('rounded-[5px] border px-2 py-1 font-mono text-[8px]', changed ? 'border-patch/30 bg-patch/[0.07] text-[#fcd34d]' : 'border-border bg-bg text-text-faint')}>{column.native_type}</span>
          </div>
        </>
      ) : (
        <div className="flex w-full items-center justify-between"><span className="text-[10px] italic text-text-faint">Field absent from live schema</span><Badge variant="danger">{kind === 'DROP' ? 'Dropped' : 'Missing'}</Badge></div>
      )}
    </div>
  )
}

export function SchemaDiffPage() {
  const { currentRun, resetVersion } = useApp()
  const [detected, setDetected] = useState<DriftEvent[]>([])
  const [catalog, setCatalog] = useState<CatalogDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.drift(), api.catalog()])
      .then(([drifts, datasets]) => {
        setDetected(drifts)
        setCatalog(datasets)
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Could not compare catalog schemas.'))
      .finally(() => setLoading(false))
  }, [resetVersion])

  const drift = detected[0] ?? currentRun?.drift ?? null
  const dataset = drift ? catalog.find((item) => item.urn === drift.dataset_urn) ?? null : null
  const rows = useMemo(() => dataset && drift ? pairColumns(dataset, drift) : [], [dataset, drift])

  if (loading) return <><PageHeader eyebrow="Live catalog comparison" title="Schema Diff" detail="Loading the baseline and live schema." /><div className="grid grid-cols-2 gap-4"><LoadingPanel rows={7} /><LoadingPanel rows={7} /></div></>

  if (!drift) {
    return (
      <div>
        <PageHeader eyebrow="Live catalog comparison" title="Schema Diff" detail="A field-level view of the detected upstream change." />
        <EmptyState icon={Braces} title="The live schema matches baseline" detail="Apply one of the controlled drift scenarios in the Control Room to see the detector's field-level evidence." />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow="Live catalog comparison"
        title="Schema Diff"
        detail={`${drift.dataset_name} · detected ${new Date(drift.detected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
        actions={<Badge variant="patch"><GitCompareArrows className="size-3" />{drift.kind === 'RENAME' ? 'Renamed' : drift.kind === 'RETYPE' ? 'Type changed' : 'Dropped'}</Badge>}
      />

      {error && <div role="alert" className="mb-4 rounded-[8px] border border-danger/30 bg-danger/10 px-4 py-2.5 text-[11px] text-[#fda4af]">{error}</div>}

      <Card className="mb-4 overflow-hidden">
        <div className="flex items-start gap-4 p-4">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-[8px] border border-patch/30 bg-patch/[0.08] text-patch"><ScanSearch className="size-4" /></div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-4">
              <h2 className="m-0 text-[12px] font-semibold text-text">Detector rationale</h2>
              <div className="flex items-center gap-2"><span className="text-[9px] text-text-faint">confidence</span><span className="font-mono text-[10px] font-semibold text-[#fbbf24]">{Math.round(drift.confidence * 100)}%</span></div>
            </div>
            <p className="mb-3 mt-1 text-[10px] leading-5 text-text-dim">{drift.rationale}</p>
            <div className="h-1.5 overflow-hidden rounded-full bg-border"><motion.div initial={{ width: 0 }} animate={{ width: `${drift.confidence * 100}%` }} transition={{ duration: 0.7, ease: motionEase }} className="h-full rounded-full bg-gradient-to-r from-patch/70 to-patch shadow-[0_0_10px_rgb(245_158_11/0.45)]" /></div>
          </div>
        </div>
      </Card>

      {dataset ? (
        <div className="relative grid grid-cols-[minmax(0,1fr)_48px_minmax(0,1fr)] items-stretch">
          <Card className="overflow-hidden">
            <div className="flex h-14 items-center justify-between border-b border-border bg-danger/[0.025] px-4">
              <div className="flex items-center gap-2"><Database className="size-3.5 text-text-faint" /><div><div className="text-[11px] font-semibold text-text">Baseline schema</div><div className="text-[8px] text-text-faint">committed snapshot</div></div></div>
              <Badge variant="neutral">Before</Badge>
            </div>
            {rows.map((row, index) => <ColumnRow key={`before-${row.before?.name ?? index}`} column={row.before} changed={row.changed} side="before" kind={drift.kind} />)}
          </Card>

          <div className="relative flex items-center justify-center">
            <div className="absolute inset-y-7 left-1/2 w-px -translate-x-1/2 bg-border" />
            <div className="relative z-10 flex size-8 items-center justify-center rounded-full border border-patch/35 bg-bg text-patch shadow-[0_0_18px_rgb(245_158_11/0.15)]"><ArrowRight className="size-3.5" /></div>
          </div>

          <Card className="overflow-hidden">
            <div className="flex h-14 items-center justify-between border-b border-border bg-ok/[0.025] px-4">
              <div className="flex items-center gap-2"><Database className="size-3.5 text-ok" /><div><div className="text-[11px] font-semibold text-text">Live DataHub schema</div><div className="text-[8px] text-text-faint">schemaMetadata · skipCache</div></div></div>
              <Badge variant="ok"><Check className="size-2.5" />After</Badge>
            </div>
            {rows.map((row, index) => <ColumnRow key={`after-${row.after?.name ?? index}`} column={row.after} changed={row.changed} side="after" kind={drift.kind} />)}
          </Card>
        </div>
      ) : (
        <EmptyState icon={Database} title="The changed dataset is not readable" detail="The drift was detected, but its live schema could not be found in the current ShopFlow catalog response." />
      )}
    </div>
  )
}
