import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function Tabs({ items, value, onValueChange, className }: {
  items: Array<{ value: string; label: ReactNode; count?: number }>
  value: string
  onValueChange: (value: string) => void
  className?: string
}) {
  return (
    <div role="tablist" className={cn('inline-flex rounded-[8px] border border-border bg-bg p-1', className)}>
      {items.map((item) => (
        <button className={cn(
            'flex h-7 cursor-pointer items-center gap-1.5 rounded-[6px] border border-transparent px-2.5 text-[11px] font-medium text-text-dim transition-all duration-200',
            item.value === value && 'border-border-lit bg-surface-2 text-text shadow-sm',
          )}
          key={item.value}
          role="tab"
          aria-selected={item.value === value}
          type="button"
          onClick={() => onValueChange(item.value)}
        >
          {item.label}
          {item.count !== undefined && <span className="font-mono text-[9px] text-text-faint">{item.count}</span>}
        </button>
      ))}
    </div>
  )
}
