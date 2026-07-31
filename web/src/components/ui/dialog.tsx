import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { motionEase } from '../../lib/utils'
import { Button } from './button'

export function Dialog({ open, onOpenChange, title, description, children }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-5 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18, ease: motionEase }}
          onMouseDown={(event) => event.target === event.currentTarget && onOpenChange(false)}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            initial={{ opacity: 0, y: 10, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.99 }}
            transition={{ duration: 0.22, ease: motionEase }}
            className="surface-elevation max-h-[86vh] w-full max-w-3xl overflow-hidden rounded-[10px] border border-border-lit bg-surface"
          >
            <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
              <div>
                <h2 id="dialog-title" className="m-0 text-[16px] font-semibold text-text">{title}</h2>
                {description && <p className="m-0 mt-1 text-[12px] text-text-dim">{description}</p>}
              </div>
              <Button aria-label="Close dialog" variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
                <X className="size-4" />
              </Button>
            </div>
            <div className="max-h-[calc(86vh-74px)] overflow-auto p-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
