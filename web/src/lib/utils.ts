import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { ImpactBucket, RepairRun } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const bucketMeta: Record<ImpactBucket, { label: string; short: string; color: string }> = {
  REQUIRES_PATCH: { label: 'Requires patch', short: 'Patch', color: 'var(--patch)' },
  DOWNSTREAM_UNAFFECTED: { label: 'Downstream unaffected', short: 'Unaffected', color: 'var(--unaffected)' },
  SKIPPED: { label: 'Correctly skipped', short: 'Skipped', color: 'var(--skipped)' },
}

export function shortUrn(urn: string) {
  const match = urn.match(/,([^,]+),PROD\)/)
  return match?.[1] ?? urn
}

export function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
}

export function timeAgo(timestamp: string) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.floor(minutes / 60)}h ago`
}

export function referenceCounts(run: RepairRun | null) {
  const references = run?.patches.flatMap((patch) => patch.references) ?? []
  const resolved = references.filter((reference) => reference.status === 'OK').length
  const sources = references.reduce<Record<string, number>>((counts, reference) => {
    counts[reference.source] = (counts[reference.source] ?? 0) + 1
    return counts
  }, {})
  return { total: references.length, resolved, sources }
}

export const motionEase = [0.22, 1, 0.36, 1] as const
