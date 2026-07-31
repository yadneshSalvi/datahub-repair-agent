import {
  Braces,
  Check,
  ChevronRight,
  CircleSlash2,
  Code2,
  FileCode2,
  FileCog,
  FileWarning,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../context/app-context'
import type { Patch, PatchKind, ReferenceCheck } from '../lib/types'
import { cn, motionEase, referenceCounts } from '../lib/utils'
import { PageHeader } from '../components/page-header'
import { Badge } from '../components/ui/badge'
import { Card } from '../components/ui/card'
import { EmptyState } from '../components/ui/empty-state'
import { LoadingPanel } from '../components/ui/skeleton'

const kindIcons: Record<PatchKind, typeof FileCode2> = {
  dbt_sql: FileCode2,
  dbt_schema_yml: Braces,
  airflow_python: TerminalSquare,
  dbt_test: FileCog,
}

interface ParsedDiffLine {
  content: string
  kind: 'header' | 'hunk' | 'add' | 'remove' | 'context'
  oldLine: number | null
  newLine: number | null
}

function parseDiff(diff: string): ParsedDiffLine[] {
  let oldLine = 0
  let newLine = 0
  return diff.split('\n').filter((line, index, lines) => !(index === lines.length - 1 && line === '')).map((line) => {
    if (line.startsWith('--- ') || line.startsWith('+++ ')) return { content: line, kind: 'header', oldLine: null, newLine: null }
    if (line.startsWith('@@')) {
      const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (match) {
        oldLine = Number(match[1])
        newLine = Number(match[2])
      }
      return { content: line, kind: 'hunk', oldLine: null, newLine: null }
    }
    if (line.startsWith('+')) return { content: line, kind: 'add', oldLine: null, newLine: newLine++ }
    if (line.startsWith('-')) return { content: line, kind: 'remove', oldLine: oldLine++, newLine: null }
    const parsed = { content: line, kind: 'context' as const, oldLine, newLine }
    oldLine += 1
    newLine += 1
    return parsed
  })
}

function UnifiedDiff({ patch }: { patch: Patch }) {
  const lines = useMemo(() => parseDiff(patch.unified_diff), [patch.unified_diff])
  return (
    <div className="max-h-[430px] overflow-auto rounded-[8px] border border-border bg-[#090b0e] font-mono text-[10px] leading-[1.55]">
      <div className="min-w-[600px] py-2">
        {lines.map((line, index) => (
          <div
            key={`${index}-${line.content}`}
            className={cn(
              'grid grid-cols-[42px_42px_minmax(0,1fr)] border-l-2 border-transparent',
              line.kind === 'add' && 'border-l-ok bg-ok/[0.08] text-[#a7f3d0]',
              line.kind === 'remove' && 'border-l-danger bg-danger/[0.08] text-[#fecdd3]',
              line.kind === 'context' && 'text-text-faint',
              line.kind === 'hunk' && 'my-1 bg-accent/[0.07] text-[#a5b4fc]',
              line.kind === 'header' && 'font-semibold text-text-dim',
            )}
          >
            <span className="select-none border-r border-border/60 px-2 text-right text-[8px] text-text-faint">{line.oldLine ?? ''}</span>
            <span className="select-none border-r border-border/60 px-2 text-right text-[8px] text-text-faint">{line.newLine ?? ''}</span>
            <span className="min-w-0 whitespace-pre-wrap break-all px-3">{line.content || ' '}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function SourceBadge({ reference }: { reference: ReferenceCheck }) {
  const labels = {
    live_catalog: 'Live catalog',
    projected_repair: 'Projected repair',
    local_cte: 'Local CTE',
    unresolved: 'Unresolved',
  }
  return <Badge variant={reference.source === 'unresolved' ? 'danger' : reference.source === 'live_catalog' ? 'ok' : 'accent'} className="whitespace-nowrap text-[8px]">{labels[reference.source]}</Badge>
}

export function PatchesPage() {
  const { currentRun, currentRunLoading } = useApp()
  const patches = currentRun?.patches ?? []
  const [selectedPath, setSelectedPath] = useState<string | null>(patches[0]?.file_path ?? null)

  useEffect(() => {
    if (patches.length && !patches.some((patch) => patch.file_path === selectedPath)) setSelectedPath(patches[0].file_path)
  }, [patches, selectedPath])

  const selected = patches.find((patch) => patch.file_path === selectedPath) ?? patches[0] ?? null
  const allReferences = patches.flatMap((patch) => patch.references.map((reference) => ({ ...reference, file_path: patch.file_path })))
  const counts = referenceCounts(currentRun)
  const invalidCount = patches.filter((patch) => !patch.valid).length
  const sourceSummary = [
    `${counts.sources.live_catalog ?? 0} live catalog`,
    `${counts.sources.projected_repair ?? 0} projected repair`,
    `${counts.sources.local_cte ?? 0} local CTE`,
  ].join(', ')

  if (currentRunLoading) return <><PageHeader eyebrow="Deterministic code generation" title="Generated Patches" detail="Loading the latest patch set." /><LoadingPanel rows={7} className="min-h-[520px]" /></>

  if (!patches.length) {
    return (
      <div>
        <PageHeader eyebrow="Deterministic code generation" title="Generated Patches" detail="Surgical diffs with a hard catalog validation gate." />
        <EmptyState icon={currentRun?.status === 'running' ? Code2 : FileCode2} title={currentRun?.status === 'running' ? 'Patch generation is in progress' : 'No generated patches yet'} detail={currentRun?.status === 'running' ? 'The agent is classifying impact before deterministic editors are allowed to change code.' : 'Start a repair run to inspect exact source changes and every reference verdict.'} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow="Deterministic code generation"
        title="Generated Patches"
        detail={`${patches.length} surgical file changes; language-model output never writes Patch.after.`}
        actions={<Badge variant={invalidCount ? 'danger' : 'ok'}><ShieldCheck className="size-3" />{invalidCount ? `${invalidCount} blocked` : 'PR gate open'}</Badge>}
      />

      <div className="grid grid-cols-[268px_minmax(0,1fr)] gap-4">
        <Card className="h-fit overflow-hidden p-2">
          <div className="px-2 pb-2 pt-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-text-faint">Repair set · {patches.length} files</div>
          <div className="space-y-1">
            {patches.map((patch, index) => {
              const Icon = kindIcons[patch.kind]
              const isSelected = selected?.file_path === patch.file_path
              return (
                <motion.button
                  key={patch.file_path}
                  type="button"
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2, delay: index * 0.03, ease: motionEase }}
                  className={cn('flex w-full cursor-pointer items-center gap-2.5 rounded-[8px] border p-2.5 text-left transition-all duration-200', isSelected ? 'border-border-lit bg-surface-2' : 'border-transparent hover:bg-surface-2/60')}
                  onClick={() => setSelectedPath(patch.file_path)}
                >
                  <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-[7px] border', patch.valid ? 'border-ok/25 bg-ok/[0.07] text-ok' : 'border-danger/25 bg-danger/[0.07] text-danger')}><Icon className="size-3.5" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[9px] font-medium text-text">{patch.file_path.split('/').at(-1)}</span>
                    <span className="mt-0.5 block truncate text-[8px] text-text-faint">{patch.file_path}</span>
                    <span className="mt-1.5 flex items-center gap-1.5"><Badge variant="patch" className="h-4 px-1.5 text-[7px]">Patch</Badge><Badge variant={patch.valid ? 'ok' : 'danger'} className="h-4 px-1.5 text-[7px]">{patch.valid ? 'Valid' : 'Blocked'}</Badge></span>
                  </span>
                  <ChevronRight className={cn('size-3 shrink-0 text-text-faint transition-transform', isSelected && 'translate-x-0.5 text-text-dim')} />
                </motion.button>
              )
            })}
          </div>
        </Card>

        {selected && (
          <div className="min-w-0 space-y-3">
            {!selected.valid && (
              <div role="alert" className="flex items-start gap-3 rounded-[8px] border border-danger/35 bg-danger/[0.08] px-4 py-3 text-[#fda4af] shadow-[inset_3px_0_0_var(--danger)]">
                <CircleSlash2 className="mt-0.5 size-4 shrink-0" />
                <div><div className="text-[11px] font-semibold">Blocked from the pull request</div><div className="mt-0.5 text-[10px] text-[#fb7185]">At least one reference could not be resolved. The validator rejected this patch before review packaging.</div></div>
              </div>
            )}
            <Card className="min-w-0 p-4">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate font-mono text-[11px] font-semibold text-text">{selected.file_path}</div>
                  <div className="mt-1 text-[9px] uppercase tracking-[0.1em] text-text-faint">{selected.kind.replaceAll('_', ' ')}</div>
                </div>
                <Badge variant={selected.valid ? 'ok' : 'danger'}>{selected.valid ? <Check className="size-3" /> : <FileWarning className="size-3" />}{selected.valid ? 'Validated' : 'Rejected'}</Badge>
              </div>
              <blockquote className="mb-4 mt-0 border-l-2 border-accent bg-accent/[0.045] px-3 py-2 text-[10px] leading-5 text-text-dim">
                {selected.strategy}
              </blockquote>
              <UnifiedDiff patch={selected} />
            </Card>
          </div>
        )}
      </div>

      <Card className="mt-4 overflow-hidden">
        <div className="flex items-center justify-between gap-5 border-b border-border px-4 py-3">
          <div>
            <h2 className="m-0 text-[13px] font-semibold text-text">Validation evidence</h2>
            <p className="m-0 mt-0.5 text-[10px] text-text-dim"><span className="font-semibold text-[#6ee7b7]">{counts.resolved}/{counts.total} resolved</span> — {sourceSummary}</p>
          </div>
          <Badge variant={counts.resolved === counts.total ? 'ok' : 'danger'}><ShieldCheck className="size-3" />Zero hallucinated columns</Badge>
        </div>
        <div className="max-h-[380px] overflow-auto">
          <table className="w-full table-fixed border-collapse text-left">
            <thead className="sticky top-0 z-10 bg-[#12151a] text-[8px] font-semibold uppercase tracking-[0.11em] text-text-faint">
              <tr>
                <th className="w-[18%] border-b border-border px-3 py-2">Table</th>
                <th className="w-[14%] border-b border-border px-3 py-2">Column</th>
                <th className="w-[7%] border-b border-border px-3 py-2">Line</th>
                <th className="w-[12%] border-b border-border px-3 py-2">Status</th>
                <th className="w-[16%] border-b border-border px-3 py-2">Resolution</th>
                <th className="border-b border-border px-3 py-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {allReferences.map((reference, index) => (
                <tr key={`${reference.file_path}-${reference.table}-${reference.column}-${reference.line}-${index}`} className="border-b border-border/60 transition-colors hover:bg-surface-2/50">
                  <td className="truncate px-3 py-2 font-mono text-[8px] text-text-dim" title={reference.table}>{reference.table}</td>
                  <td className="truncate px-3 py-2 font-mono text-[9px] text-text">{reference.column}</td>
                  <td className="px-3 py-2 font-mono text-[8px] text-text-faint">{reference.line ?? '—'}</td>
                  <td className="px-3 py-2"><Badge variant={reference.status === 'OK' ? 'ok' : 'danger'} className="h-5 text-[8px]">{reference.status === 'OK' && <Check className="size-2.5" />}{reference.status}</Badge></td>
                  <td className="px-3 py-2"><SourceBadge reference={reference} /></td>
                  <td className="px-3 py-2 text-[9px] leading-4 text-text-dim">{reference.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!allReferences.length && <div className="flex h-28 items-center justify-center text-[10px] text-text-faint">This metadata-only patch contains no executable column references.</div>}
        </div>
      </Card>
    </div>
  )
}
