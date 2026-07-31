import {
  Activity,
  Boxes,
  Braces,
  GitPullRequest,
  Network,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  WandSparkles,
} from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { useState } from 'react'
import { useApp } from '../context/app-context'
import { cn, motionEase, timeAgo } from '../lib/utils'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Separator } from './ui/separator'
import { Tooltip } from './ui/tooltip'

const nav = [
  { to: '/', label: 'Control Room', icon: Activity },
  { to: '/schema', label: 'Schema Diff', icon: Braces },
  { to: '/impact', label: 'Impact Graph', icon: Network },
  { to: '/patches', label: 'Patches', icon: ScanSearch },
  { to: '/pr', label: 'Pull Request', icon: GitPullRequest },
  { to: '/writeback', label: 'Write-Back', icon: ShieldCheck },
]

export function AppShell() {
  const location = useLocation()
  const { health, healthLoading, healthError, currentRun, resetDemo, resetting } = useApp()
  const [resetError, setResetError] = useState<string | null>(null)
  const deterministicMode = currentRun ? currentRun.mode === 'deterministic' : Boolean(health && !health.llm_available)

  const handleReset = async () => {
    setResetError(null)
    try {
      await resetDemo()
    } catch (error) {
      setResetError(error instanceof Error ? error.message : 'The demo could not be reset.')
    }
  }

  return (
    <div className="min-h-screen bg-transparent text-text">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-border bg-[#0a0c0f]/95 px-3 pb-3 pt-4 backdrop-blur-xl">
        <div className="flex items-center gap-3 px-2 pb-5">
          <div className="relative flex size-9 shrink-0 items-center justify-center rounded-[9px] border border-accent/30 bg-accent/10 text-[#a5b4fc] shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]">
            <Boxes className="size-[18px]" />
            <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-[#0a0c0f] bg-ok" />
          </div>
          <div className="leading-tight">
            <div className="text-[12px] font-semibold text-text">Schema-Drift</div>
            <div className="text-[11px] text-text-dim">Auto-Repair Agent</div>
          </div>
        </div>

        <div className="px-2 pb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-text-faint">Repair workflow</div>
        <nav aria-label="Primary" className="space-y-1">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => cn(
                'group flex h-10 items-center gap-3 rounded-[8px] border border-transparent px-3 text-[12px] font-medium text-text-dim transition-all duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] hover:bg-surface-2 hover:text-text',
                isActive && 'border-border-lit bg-surface-2 text-text shadow-[inset_3px_0_0_var(--accent),inset_0_1px_0_rgb(255_255_255/0.04)]',
              )}
            >
              <Icon className="size-4 text-text-faint transition-colors group-hover:text-text-dim" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-2">
          <Separator className="mb-3" />
          <div className="rounded-[8px] border border-border bg-surface px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-faint">DataHub</span>
              <span className={cn('size-1.5 rounded-full', health?.datahub_reachable ? 'bg-ok shadow-[0_0_8px_var(--ok)]' : 'bg-danger')} />
            </div>
            <div className="mt-1 truncate font-mono text-[10px] text-text-dim">
              {healthLoading ? 'checking connection' : health?.gms_url ?? healthError ?? 'unreachable'}
            </div>
          </div>
          <div className={cn(
            'rounded-[8px] border px-3 py-2.5',
            deterministicMode ? 'border-patch/20 bg-patch/[0.06]' : 'border-accent/20 bg-accent/[0.06]',
          )}>
            <div className="flex items-center gap-2">
              <WandSparkles className={cn('size-3.5', deterministicMode ? 'text-patch' : 'text-[#a5b4fc]')} />
              <span className="text-[10px] font-semibold text-text">
                {deterministicMode ? 'Deterministic mode' : 'gpt-5.6-sol'}
              </span>
            </div>
            <div className="mt-0.5 text-[9px] text-text-faint">
              {deterministicMode ? 'Repair engine remains active' : 'MCP reasoning available'}
            </div>
          </div>
        </div>
      </aside>

      <div className="ml-[248px] min-h-screen min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-bg/85 px-6 backdrop-blur-xl">
          <div className="flex min-w-0 items-center gap-3">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-faint">Current run</span>
            {currentRun ? (
              <>
                <Tooltip content={currentRun.id}>
                  <span className="max-w-[260px] truncate font-mono text-[10px] text-text-dim">{currentRun.id}</span>
                </Tooltip>
                <Badge variant={currentRun.status === 'succeeded' ? 'ok' : currentRun.status === 'failed' ? 'danger' : 'accent'}>
                  {currentRun.status === 'running' && <span className="size-1 rounded-full bg-current [animation:status-pulse_1.2s_ease-in-out_infinite]" />}
                  {currentRun.status}
                </Badge>
                {currentRun.degraded && <Badge variant="patch">degraded</Badge>}
                <Badge variant="neutral">{currentRun.mode}</Badge>
                <span className="hidden text-[10px] text-text-faint xl:inline">started {timeAgo(currentRun.started_at)}</span>
              </>
            ) : (
              <span className="text-[11px] text-text-faint">No run selected</span>
            )}
          </div>
          <Button variant="outline" size="sm" disabled={resetting} onClick={() => void handleReset()}>
            <RotateCcw className={cn('size-3.5', resetting && 'animate-spin')} />
            {resetting ? 'Resetting' : 'Reset demo'}
          </Button>
        </header>

        <AnimatePresence mode="wait">
          <motion.main
            key={location.pathname}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={{ duration: 0.2, ease: motionEase }}
            className="min-w-0 px-6 py-5"
          >
            {(healthError || resetError) && (
              <div role="alert" className="mb-4 flex items-center gap-2 rounded-[8px] border border-danger/30 bg-danger/10 px-3 py-2 text-[11px] text-[#fda4af]">
                <span className="size-1.5 rounded-full bg-danger" />
                {resetError ?? healthError}
              </div>
            )}
            {health && !health.llm_available && !currentRun?.degraded && (
              <div className="mb-4 flex items-center justify-between gap-4 rounded-[8px] border border-patch/25 bg-patch/[0.07] px-3 py-2 text-[11px] text-[#fcd34d]">
                <span>No OpenAI key is configured. Deterministic mode remains fully operational for patches, validation, PR packaging, and write-back.</span>
                <Badge variant="patch">deterministic</Badge>
              </div>
            )}
            {currentRun?.degraded && (
              <div className="mb-4 flex items-center justify-between gap-4 rounded-[8px] border border-danger/30 bg-danger/[0.07] px-3 py-2 text-[11px] text-[#fda4af]">
                <span>{currentRun.degradations.at(-1) ?? 'A dependency failed and the run continued with reduced capabilities.'}</span>
                <Badge variant="danger">degraded</Badge>
              </div>
            )}
            <Outlet />
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  )
}
