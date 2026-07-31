import { cn } from '../../lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-[8px] bg-surface-2', className)} />
}

export function LoadingPanel({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('surface-elevation rounded-[10px] border border-border bg-surface p-5', className)}>
      <Skeleton className="mb-5 h-5 w-44" />
      <div className="space-y-3">
        {Array.from({ length: rows }, (_, index) => (
          <Skeleton key={index} className={cn('h-12 w-full', index === rows - 1 && 'w-4/5')} />
        ))}
      </div>
    </div>
  )
}
