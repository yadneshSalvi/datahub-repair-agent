import { useEffect, useRef, useState } from 'react'
import type { RunEvent } from './types'

interface RunStreamState {
  events: RunEvent[]
  connected: boolean
  finished: boolean
  error: string | null
  reconnects: number
}

export function useRunStream(runId: string | null, seedEvents: RunEvent[] = []): RunStreamState {
  const [events, setEvents] = useState<RunEvent[]>(seedEvents)
  const [connected, setConnected] = useState(false)
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reconnects, setReconnects] = useState(0)
  const retryRef = useRef<number | null>(null)

  useEffect(() => {
    setEvents(seedEvents)
    setFinished(false)
    setError(null)
  }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!runId || finished) return

    let source: EventSource | null = null
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      source = new EventSource(`/api/runs/${runId}/events`)

      source.onopen = () => {
        setConnected(true)
        setError(null)
      }

      source.onmessage = (frame) => {
        try {
          const event = JSON.parse(frame.data) as RunEvent
          setEvents((current) => {
            if (current.some((item) => item.seq === event.seq)) return current
            return [...current, event].sort((left, right) => left.seq - right.seq)
          })
        } catch {
          setError('A progress frame could not be decoded. Reconnecting to the run stream.')
        }
      }

      source.addEventListener('done', () => {
        setFinished(true)
        setConnected(false)
        source?.close()
      })

      source.onerror = () => {
        setConnected(false)
        source?.close()
        if (cancelled) return
        setError('Live progress paused. Reconnecting automatically.')
        setReconnects((value) => value + 1)
        retryRef.current = window.setTimeout(connect, 1200)
      }
    }

    connect()
    return () => {
      cancelled = true
      source?.close()
      if (retryRef.current !== null) window.clearTimeout(retryRef.current)
    }
  }, [finished, runId])

  return { events, connected, finished, error, reconnects }
}
