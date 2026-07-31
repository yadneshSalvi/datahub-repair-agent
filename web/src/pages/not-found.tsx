import { ArrowLeft, FileQuestion, Radar } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { Badge } from '../components/ui/badge'
import { Card } from '../components/ui/card'

export function NotFoundPage() {
  const location = useLocation()
  return (
    <div className="flex min-h-[calc(100vh-7.5rem)] items-center justify-center">
      <Card className="relative w-full max-w-2xl overflow-hidden border-accent/25 bg-[radial-gradient(circle_at_top_right,rgb(99_102_241/0.13),transparent_42%)] p-10 text-center">
        <Radar className="absolute -right-12 -top-12 size-48 text-accent/[0.05]" />
        <div className="relative mx-auto flex size-12 items-center justify-center rounded-[12px] border border-accent/30 bg-accent/10 text-[#a5b4fc]">
          <FileQuestion className="size-6" />
        </div>
        <Badge variant="accent" className="mt-5">404 · route not found</Badge>
        <h1 className="mb-2 mt-4 text-[24px] font-semibold tracking-[-0.02em] text-text">This evidence path does not exist.</h1>
        <p className="mx-auto mb-0 max-w-md text-[11px] leading-5 text-text-dim">
          <code className="rounded-[4px] border border-border bg-bg px-1.5 py-0.5 text-[#c7d2fe]">{location.pathname}</code> is not part of the repair workspace.
          Return to the Control Room to start or inspect a schema-drift run.
        </p>
        <Link to="/" className="mx-auto mt-6 inline-flex h-10 items-center gap-2 rounded-[8px] border border-accent bg-accent px-4 text-[12px] font-semibold text-white no-underline shadow-[0_8px_24px_rgb(99_102_241/0.2)] transition-colors hover:bg-[#7476f3]">
          <ArrowLeft className="size-3.5" />
          Back to Control Room
        </Link>
      </Card>
    </div>
  )
}
