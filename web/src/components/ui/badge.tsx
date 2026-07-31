import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

type BadgeVariant = 'neutral' | 'accent' | 'ok' | 'danger' | 'patch' | 'unaffected' | 'skipped'

const variants: Record<BadgeVariant, string> = {
  neutral: 'border-border-lit bg-surface-2 text-text-dim',
  accent: 'border-accent/35 bg-accent/10 text-[#a5b4fc]',
  ok: 'border-ok/35 bg-ok/10 text-[#6ee7b7]',
  danger: 'border-danger/35 bg-danger/10 text-[#fb7185]',
  patch: 'border-patch/35 bg-patch/10 text-[#fbbf24]',
  unaffected: 'border-unaffected/35 bg-unaffected/10 text-[#7dd3fc]',
  skipped: 'border-skipped bg-skipped/15 text-[#9ca3af]',
}

export function Badge({ className, variant = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-[6px] border px-2 text-[10px] font-semibold uppercase tracking-[0.08em]',
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
