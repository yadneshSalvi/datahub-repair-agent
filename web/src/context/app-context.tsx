import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { HealthResponse, RepairRun } from '../lib/types'
import { useRunStream } from '../lib/useRunStream'

interface AppContextValue {
  health: HealthResponse | null
  healthLoading: boolean
  healthError: string | null
  currentRun: RepairRun | null
  currentRunLoading: boolean
  streamConnected: boolean
  streamError: string | null
  setCurrentRun: (run: RepairRun | null) => void
  startRunState: (runId: string) => void
  refreshRun: () => Promise<void>
  refreshHealth: () => Promise<void>
  resetDemo: () => Promise<void>
  resetting: boolean
  resetVersion: number
}

const AppContext = createContext<AppContextValue | null>(null)

function placeholderRun(id: string): RepairRun {
  return {
    id,
    status: 'running',
    degraded: false,
    degradations: [],
    drift: null,
    impact: null,
    patches: [],
    pr: null,
    writeback: [],
    events: [],
    started_at: new Date().toISOString(),
    finished_at: null,
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [currentRun, setCurrentRun] = useState<RepairRun | null>(null)
  const [currentRunLoading, setCurrentRunLoading] = useState(true)
  const [resetting, setResetting] = useState(false)
  const [resetVersion, setResetVersion] = useState(0)
  const stream = useRunStream(currentRun?.status === 'running' ? currentRun.id : null, currentRun?.events)

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true)
    try {
      setHealth(await api.health())
      setHealthError(null)
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : 'Health check failed.')
    } finally {
      setHealthLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshHealth()
    Promise.all([api.runs(), api.drift()])
      .then(([runs, drifts]) => setCurrentRun(drifts.length ? runs[0] ?? null : null))
      .catch(() => setCurrentRun(null))
      .finally(() => setCurrentRunLoading(false))
  }, [refreshHealth])

  useEffect(() => {
    if (!currentRun || stream.events.length === 0) return
    setCurrentRun((run) => run ? { ...run, events: stream.events } : run)
  }, [stream.events])

  const refreshRun = useCallback(async () => {
    if (!currentRun?.id) return
    const run = await api.run(currentRun.id)
    setCurrentRun(run)
  }, [currentRun?.id])

  useEffect(() => {
    if (stream.finished) void refreshRun()
  }, [refreshRun, stream.finished])

  const startRunState = useCallback((runId: string) => {
    setCurrentRun(placeholderRun(runId))
  }, [])

  const resetDemo = useCallback(async () => {
    setResetting(true)
    try {
      await api.reset()
      setCurrentRun(null)
      setResetVersion((version) => version + 1)
      await refreshHealth()
    } finally {
      setResetting(false)
    }
  }, [refreshHealth])

  const value = useMemo<AppContextValue>(() => ({
    health,
    healthLoading,
    healthError,
    currentRun,
    currentRunLoading,
    streamConnected: stream.connected,
    streamError: stream.error,
    setCurrentRun,
    startRunState,
    refreshRun,
    refreshHealth,
    resetDemo,
    resetting,
    resetVersion,
  }), [
    currentRun,
    currentRunLoading,
    health,
    healthError,
    healthLoading,
    refreshHealth,
    refreshRun,
    resetDemo,
    resetting,
    resetVersion,
    startRunState,
    stream.connected,
    stream.error,
  ])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used inside AppProvider.')
  return context
}
