import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components/app-shell'
import { Skeleton } from './components/ui/skeleton'

const ControlRoom = lazy(() => import('./pages/control-room').then((module) => ({ default: module.ControlRoom })))
const SchemaDiffPage = lazy(() => import('./pages/schema-diff').then((module) => ({ default: module.SchemaDiffPage })))
const ImpactGraphPage = lazy(() => import('./pages/impact-graph').then((module) => ({ default: module.ImpactGraphPage })))
const PatchesPage = lazy(() => import('./pages/patches').then((module) => ({ default: module.PatchesPage })))
const PullRequestPage = lazy(() => import('./pages/pull-request').then((module) => ({ default: module.PullRequestPage })))
const WritebackPage = lazy(() => import('./pages/writeback').then((module) => ({ default: module.WritebackPage })))
const NotFoundPage = lazy(() => import('./pages/not-found').then((module) => ({ default: module.NotFoundPage })))

function RouteFallback() {
  return (
    <div className="space-y-4" aria-label="Loading workspace">
      <div className="flex items-end justify-between"><div><Skeleton className="mb-2 h-2.5 w-28" /><Skeleton className="h-7 w-52" /></div><Skeleton className="h-8 w-32" /></div>
      <Skeleton className="h-[480px] w-full rounded-[10px] border border-border" />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Suspense fallback={<RouteFallback />}><ControlRoom /></Suspense>} />
        <Route path="schema" element={<Suspense fallback={<RouteFallback />}><SchemaDiffPage /></Suspense>} />
        <Route path="impact" element={<Suspense fallback={<RouteFallback />}><ImpactGraphPage /></Suspense>} />
        <Route path="patches" element={<Suspense fallback={<RouteFallback />}><PatchesPage /></Suspense>} />
        <Route path="pr" element={<Suspense fallback={<RouteFallback />}><PullRequestPage /></Suspense>} />
        <Route path="writeback" element={<Suspense fallback={<RouteFallback />}><WritebackPage /></Suspense>} />
        <Route path="*" element={<Suspense fallback={<RouteFallback />}><NotFoundPage /></Suspense>} />
      </Route>
    </Routes>
  )
}
