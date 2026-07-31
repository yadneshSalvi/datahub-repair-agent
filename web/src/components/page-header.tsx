import type { ReactNode } from 'react'

export function PageHeader({ eyebrow, title, detail, actions }: {
  eyebrow: string
  title: string
  detail: string
  actions?: ReactNode
}) {
  return (
    <header className="mb-5 flex min-h-14 items-end justify-between gap-6">
      <div className="min-w-0">
        <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-text-faint">{eyebrow}</div>
        <div className="flex items-baseline gap-3">
          <h1 className="m-0 text-[24px] font-semibold leading-none text-text">{title}</h1>
          <p className="m-0 hidden max-w-2xl truncate text-[12px] text-text-dim xl:block">{detail}</p>
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}
