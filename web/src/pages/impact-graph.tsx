import dagre from 'dagre'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeProps,
} from '@xyflow/react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowRight,
  ExternalLink,
  Filter,
  GitBranch,
  Layers3,
  Network,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useApp } from '../context/app-context'
import type { ImpactBucket, ImpactedAsset, LineageNode } from '../lib/types'
import { bucketMeta, cn, motionEase, shortUrn } from '../lib/utils'
import { PageHeader } from '../components/page-header'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { EmptyState } from '../components/ui/empty-state'
import { LoadingPanel } from '../components/ui/skeleton'

interface ImpactNodeData extends Record<string, unknown> {
  lineage: LineageNode
  asset: ImpactedAsset | null
  driftColumn: string | null
}

type ImpactFlowNode = FlowNode<ImpactNodeData, 'impact'>

function platformFor(node: LineageNode) {
  if (node.urn.includes('dataPlatform:snowflake')) return 'snowflake'
  if (node.urn.includes('dataPlatform:dbt')) return 'dbt'
  if (node.urn.includes('dataFlow:(airflow')) return 'airflow'
  return 'datahub'
}

function ImpactNodeCard({ data }: NodeProps<ImpactFlowNode>) {
  const { lineage, driftColumn } = data
  const bucket = lineage.bucket
  const platform = platformFor(lineage)
  const nodeColor = bucket ? bucketMeta[bucket].color : 'var(--accent)'
  return (
    <div
      className={cn(
        'w-[200px] rounded-[9px] border bg-[#111419] px-3 py-2.5 shadow-[inset_0_1px_0_rgb(255_255_255/0.04),0_8px_24px_rgb(0_0_0/0.24)] transition-all duration-200 hover:-translate-y-0.5',
        bucket === 'SKIPPED' && 'opacity-55',
      )}
      style={{ borderColor: `color-mix(in srgb, ${nodeColor} 52%, transparent)`, boxShadow: `inset 3px 0 0 ${nodeColor}, inset 0 1px 0 rgb(255 255 255 / 0.04), 0 0 18px color-mix(in srgb, ${nodeColor} 10%, transparent)` }}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-text-faint" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] font-semibold text-text">{lineage.name}</span>
        <span className="rounded-[4px] border border-border-lit bg-surface-2 px-1.5 py-0.5 text-[7px] font-bold uppercase tracking-[0.1em] text-text-faint">{platform}</span>
      </div>
      <div className="mt-0.5 text-[8px] uppercase tracking-[0.08em] text-text-faint">{lineage.kind.replaceAll('_', ' ')}</div>
      {/* Single non-wrapping row: every card must keep a uniform height or the fixed
          row pitch in layoutGraph() overlaps neighbouring ranks. */}
      <div className="mt-2 flex h-5 flex-nowrap items-center gap-1 overflow-hidden">
        {lineage.columns.length ? lineage.columns.slice(0, 2).map((column) => (
          <span key={column} className={cn(
            'min-w-0 shrink truncate rounded-[4px] border border-border-lit bg-bg px-1.5 py-0.5 font-mono text-[8px] text-text-dim',
            column === driftColumn && 'border-patch/40 bg-patch/10 text-[#fcd34d]',
          )}>{column}</span>
        )) : <span className="text-[8px] italic text-text-faint">outside column path</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-text-faint" />
    </div>
  )
}

const nodeTypes = { impact: ImpactNodeCard }

/** Rendered card box. Must match ImpactNodeCard, which is fixed-height by design. */
const NODE_WIDTH = 200
const NODE_HEIGHT = 84
/** Gaps between cards. ROW_PITCH > NODE_HEIGHT is what keeps ranks from colliding. */
const ROW_PITCH = NODE_HEIGHT + 18
const COL_PITCH = NODE_WIDTH + 46

function layoutGraph(nodes: LineageNode[], enabled: Set<ImpactBucket>) {
  const visible = nodes.filter((node) => node.bucket === null || enabled.has(node.bucket))
  const visibleUrns = new Set(visible.map((node) => node.urn))
  const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  dagreGraph.setGraph({ rankdir: 'LR', ranksep: 62, nodesep: 15, marginx: 16, marginy: 16 })
  visible.forEach((node) => dagreGraph.setNode(node.urn, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  return { visible, visibleUrns, dagreGraph }
}

export function ImpactGraphPage() {
  const { currentRun, currentRunLoading } = useApp()
  const report = currentRun?.impact ?? null
  const [enabled, setEnabled] = useState<Set<ImpactBucket>>(new Set(['REQUIRES_PATCH', 'DOWNSTREAM_UNAFFECTED', 'SKIPPED']))
  const [selectedUrn, setSelectedUrn] = useState<string | null>(null)

  const graphElements = useMemo(() => {
    if (!report) return { nodes: [] as ImpactFlowNode[], edges: [] as FlowEdge[] }
    const { visible, visibleUrns, dagreGraph } = layoutGraph(report.graph.nodes, enabled)
    report.graph.edges.forEach((edge) => {
      if (visibleUrns.has(edge.source_urn) && visibleUrns.has(edge.target_urn)) dagreGraph.setEdge(edge.source_urn, edge.target_urn)
    })
    dagre.layout(dagreGraph)

    const ranks = new Map<number, LineageNode[]>()
    visible.forEach((node) => {
      const rank = node.hops ?? 0
      ranks.set(rank, [...(ranks.get(rank) ?? []), node])
    })
    ranks.forEach((rankNodes, rank) => {
      ranks.set(rank, [...rankNodes].sort((left, right) => {
        const leftY = (dagreGraph.node(left.urn) as { y?: number } | undefined)?.y ?? 0
        const rightY = (dagreGraph.node(right.urn) as { y?: number } | undefined)?.y ?? 0
        return leftY - rightY
      }))
    })

    const positioned = visible.map((node) => {
      const rank = node.hops ?? 0
      const peers = ranks.get(rank) ?? [node]
      const peerIndex = peers.findIndex((peer) => peer.urn === node.urn)
      const normalizedY = 20 + peerIndex * ROW_PITCH + Math.max(0, 5 - peers.length) * 8
      return {
        id: node.urn,
        type: 'impact' as const,
        position: { x: 18 + rank * COL_PITCH, y: normalizedY },
        data: {
          lineage: node,
          asset: report.assets.find((asset) => asset.urn === node.urn) ?? null,
          driftColumn: report.drift.old_column,
        },
      }
    })

    const edges = report.graph.edges
      .filter((edge) => visibleUrns.has(edge.source_urn) && visibleUrns.has(edge.target_urn))
      .map((edge, index) => {
        const onDriftPath = edge.source_columns.includes(report.drift.old_column ?? '') || edge.target_columns.includes(report.drift.old_column ?? '')
        return {
          id: `${edge.source_urn}-${edge.target_urn}-${index}`,
          source: edge.source_urn,
          target: edge.target_urn,
          label: edge.transform_operation ?? 'LINEAGE',
          animated: onDriftPath,
          type: 'smoothstep',
          style: { stroke: onDriftPath ? 'var(--patch)' : 'var(--border-lit)', strokeWidth: onDriftPath ? 1.8 : 1 },
          labelStyle: { fill: onDriftPath ? '#fbbf24' : '#6b7280', fontSize: 8, fontFamily: 'JetBrains Mono' },
          labelBgStyle: { fill: '#0e1013', fillOpacity: 0.96 },
          markerEnd: { type: 'arrowclosed' as const, color: onDriftPath ? 'var(--patch)' : 'var(--border-lit)', width: 12, height: 12 },
        }
      })
    return { nodes: positioned, edges }
  }, [enabled, report])

  const selectedNode = report?.graph.nodes.find((node) => node.urn === selectedUrn) ?? null
  const selectedAsset = report?.assets.find((asset) => asset.urn === selectedUrn) ?? null
  const skipped = report?.assets.filter((asset) => asset.bucket === 'SKIPPED') ?? []

  const toggleBucket = (bucket: ImpactBucket) => {
    setEnabled((current) => {
      const next = new Set(current)
      if (next.has(bucket)) next.delete(bucket)
      else next.add(bucket)
      return next
    })
  }

  if (currentRunLoading) return <><PageHeader eyebrow="Column-level lineage" title="Impact Graph" detail="Loading the latest repair evidence." /><LoadingPanel rows={6} className="min-h-[500px]" /></>

  if (!report) {
    return (
      <div>
        <PageHeader eyebrow="Column-level lineage" title="Impact Graph" detail="The exact blast radius, classified with DataHub column evidence." />
        <EmptyState icon={currentRun?.status === 'running' ? GitBranch : Network} title={currentRun?.status === 'running' ? 'Tracing the changed column' : 'No impact report yet'} detail={currentRun?.status === 'running' ? 'The agent is reading lineage and exact code references. This view will populate when classification completes.' : 'Run a repair from the Control Room to generate an evidence-backed impact graph.'} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow="Column-level lineage"
        title="Impact Graph"
        detail={`${report.stats.total_scanned ?? report.assets.length} assets classified across ${report.stats.max_hops_reached ?? 0} lineage hops.`}
        actions={<Badge variant="accent"><Network className="size-3" /> DataHub fine-grained lineage</Badge>}
      />

      <Card className="overflow-hidden">
        <div className="grid h-[410px] grid-cols-[178px_minmax(0,1fr)]">
          <aside className="border-r border-border bg-[#0b0d10] p-3">
            <div className="mb-4 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-faint"><Filter className="size-3" />Visible evidence</div>
            <div className="space-y-2">
              {(Object.keys(bucketMeta) as ImpactBucket[]).map((bucket) => {
                const meta = bucketMeta[bucket]
                const count = report.assets.filter((asset) => asset.bucket === bucket).length
                return (
                  <button className={cn('flex w-full cursor-pointer items-center justify-between rounded-[8px] border px-2.5 py-2 text-left transition-all duration-200', enabled.has(bucket) ? 'border-border-lit bg-surface-2' : 'border-transparent bg-transparent opacity-45')}
                    key={bucket}
                    type="button"
                    onClick={() => toggleBucket(bucket)}
                  >
                    <span className="flex items-center gap-2">
                      <span className="size-2 rounded-[3px]" style={{ background: meta.color, boxShadow: enabled.has(bucket) ? `0 0 9px ${meta.color}` : 'none' }} />
                      <span className="text-[10px] font-medium text-text-dim">{meta.short}</span>
                    </span>
                    <span className="font-mono text-[9px] text-text-faint">{count}</span>
                  </button>
                )
              })}
            </div>
            <div className="mt-5 border-t border-border pt-4">
              <div className="mb-2 text-[9px] font-semibold uppercase tracking-[0.12em] text-text-faint">Reading the graph</div>
              <p className="m-0 text-[9px] leading-4 text-text-faint">Animated amber edges trace the drifted column. Select any node to inspect its decision evidence.</p>
            </div>
            <div className="mt-4 rounded-[8px] border border-patch/20 bg-patch/[0.05] px-2.5 py-2">
              <div className="font-mono text-[10px] font-semibold text-[#fbbf24]">{report.drift.old_column}</div>
              <div className="mt-0.5 text-[8px] text-text-faint">origin column</div>
            </div>
          </aside>
          <div className="dot-grid relative min-w-0 bg-[#0a0c0f]">
            <ReactFlow
              nodes={graphElements.nodes}
              edges={graphElements.edges}
              nodeTypes={nodeTypes}
              minZoom={0.38}
              maxZoom={1.25}
              fitView
              fitViewOptions={{ padding: 0.1, maxZoom: 1 }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
              onNodeClick={(_, node) => setSelectedUrn(node.id)}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="transparent" />
              <Controls showInteractive={false} position="bottom-left" />
            </ReactFlow>
            {/* Bottom-right: fitView packs nodes against the top edge, so a top-anchored
                badge lands on top of the last rank's node titles. */}
            <div className="pointer-events-none absolute bottom-3 right-3 rounded-[6px] border border-border bg-bg/85 px-2 py-1 font-mono text-[8px] text-text-faint backdrop-blur-sm">left to right · {report.stats.max_hops_reached ?? 3} hops</div>
          </div>
        </div>
      </Card>

      <Card className="mt-4 border-skipped/70 bg-[linear-gradient(135deg,rgb(75_85_99/0.09),transparent_60%)] p-4">
        <div className="mb-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-[8px] border border-skipped bg-skipped/15 text-[#9ca3af]"><ShieldCheck className="size-4" /></div>
            <div>
              <h2 className="m-0 text-[13px] font-semibold text-text">Correctly skipped</h2>
              <p className="m-0 mt-0.5 text-[10px] text-text-faint">Explicit negative evidence proves the agent did not confuse table lineage with column impact.</p>
            </div>
          </div>
          <Badge variant="skipped">{skipped.length} precision decisions</Badge>
        </div>
        <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
          {skipped.map((asset) => (
            <button className="group cursor-pointer rounded-[8px] border border-border bg-bg/55 px-3 py-2.5 text-left transition-all duration-200 hover:border-skipped hover:bg-surface-2"
              key={asset.urn}
              type="button"
              onClick={() => setSelectedUrn(asset.urn)}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-semibold text-text-dim group-hover:text-text">{asset.name}</span>
                <span className="font-mono text-[8px] text-text-faint">hop {asset.hops ?? '—'}</span>
              </span>
              <span className="mt-1 block line-clamp-2 text-[9px] leading-4 text-text-faint">{asset.reason}</span>
            </button>
          ))}
        </div>
      </Card>

      <AnimatePresence>
        {selectedNode && (
          <motion.aside
            initial={{ x: 380, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 380, opacity: 0 }}
            transition={{ duration: 0.22, ease: motionEase }}
            className="fixed bottom-0 right-0 top-14 z-50 w-[390px] overflow-y-auto border-l border-border-lit bg-[#0c0e11]/98 p-5 shadow-[-18px_0_42px_rgb(0_0_0/0.38)] backdrop-blur-xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <Badge variant={selectedNode.bucket === 'REQUIRES_PATCH' ? 'patch' : selectedNode.bucket === 'DOWNSTREAM_UNAFFECTED' ? 'unaffected' : selectedNode.bucket === 'SKIPPED' ? 'skipped' : 'accent'}>
                  {selectedNode.bucket ? bucketMeta[selectedNode.bucket].label : 'Drift source'}
                </Badge>
                <h2 className="mb-0 mt-3 truncate text-[18px] font-semibold text-text">{selectedNode.name}</h2>
                <div className="mt-1 font-mono text-[9px] text-text-faint">{selectedNode.kind.replaceAll('_', ' ')} · hop {selectedNode.hops ?? 0}</div>
              </div>
              <Button aria-label="Close evidence panel" variant="ghost" size="icon" onClick={() => setSelectedUrn(null)}><X className="size-4" /></Button>
            </div>

            <div className="mt-5 space-y-5">
              <EvidenceSection title="Matched columns">
                <div className="flex flex-wrap gap-1.5">
                  {selectedNode.columns.length ? selectedNode.columns.map((column) => <span key={column} className={cn('rounded-[5px] border border-border-lit bg-surface-2 px-2 py-1 font-mono text-[9px] text-text-dim', column === report.drift.old_column && 'border-patch/40 bg-patch/10 text-[#fcd34d]')}>{column}</span>) : <span className="text-[10px] italic text-text-faint">No column on the drift path.</span>}
                </div>
              </EvidenceSection>

              <EvidenceSection title="Classification reason">
                <p className="m-0 rounded-[8px] border border-border bg-surface p-3 text-[10px] leading-5 text-text-dim">{selectedAsset?.reason ?? 'This is the upstream drift source and the origin of the lineage trace.'}</p>
              </EvidenceSection>

              <EvidenceSection title="Captured queries">
                {selectedAsset?.captured_queries.length ? selectedAsset.captured_queries.map((query) => <pre key={query} className="m-0 overflow-x-auto rounded-[8px] border border-border bg-bg p-3 text-[9px] text-text-dim">{query}</pre>) : <div className="rounded-[8px] border border-dashed border-border p-3 text-[9px] text-text-faint">No usage query text was captured in this window. Fine-grained lineage remains the impact authority.</div>}
              </EvidenceSection>

              <EvidenceSection title="Lineage path">
                {selectedAsset?.lineage_path.length ? (
                  <div className="space-y-2">
                    {selectedAsset.lineage_path.map((hop, index) => (
                      <div key={`${hop.upstream_urn}-${hop.downstream_urn}-${index}`} className="rounded-[8px] border border-border bg-surface p-2.5">
                        <div className="flex items-center gap-2 font-mono text-[8px] text-text-dim">
                          <span className="max-w-[118px] truncate">{shortUrn(hop.upstream_urn)}.{hop.upstream_column}</span>
                          <ArrowRight className="size-3 shrink-0 text-patch" />
                          <span className="max-w-[118px] truncate">{shortUrn(hop.downstream_urn)}.{hop.downstream_column}</span>
                        </div>
                        <div className="mt-1 text-[8px] font-semibold uppercase tracking-[0.1em] text-text-faint">{hop.transform_operation ?? 'lineage'} · hop {hop.hops ?? index + 1}</div>
                      </div>
                    ))}
                  </div>
                ) : <div className="text-[9px] text-text-faint">{selectedNode.bucket === null ? 'This upstream dataset is the origin of the drift-column lineage trace.' : 'No drift-column lineage path reaches this asset. That absence is the skip evidence.'}</div>}
              </EvidenceSection>
            </div>

            {selectedNode.datahub_url && (
              <a href={selectedNode.datahub_url} target="_blank" rel="noreferrer" className="mt-6 flex h-10 items-center justify-center gap-2 rounded-[8px] border border-accent/35 bg-accent/10 text-[11px] font-semibold text-[#a5b4fc] no-underline transition-colors hover:bg-accent/20">
                View in DataHub <ExternalLink className="size-3.5" />
              </a>
            )}
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  )
}

function EvidenceSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 mt-0 flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.13em] text-text-faint"><Layers3 className="size-3" />{title}</h3>
      {children}
    </section>
  )
}
