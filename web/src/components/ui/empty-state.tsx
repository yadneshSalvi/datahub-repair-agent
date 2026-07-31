import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function EmptyState({ icon: Icon, title, detail, action, className }: {
  icon: LucideIcon
  title: string
  detail: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-h-64 flex-col items-center justify-center rounded-[10px] border border-dashed border-border-lit bg-surface/60 px-8 py-10 text-center', className)}>
      <div className="mb-4 flex size-10 items-center justify-center rounded-[9px] border border-border-lit bg-surface-2 text-text-dim">
        <Icon className="size-[18px]" />
      </div>
      <h2 className="m-0 text-[15px] font-semibold text-text">{title}</h2>
      <p className="mb-0 mt-1 max-w-md text-[12px] leading-5 text-text-dim">{detail}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
