import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { motionEase } from '../../lib/utils'

export function Tooltip({ children, content }: { children: ReactNode; content: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      <AnimatePresence>
        {open && (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 2 }}
            transition={{ duration: 0.18, ease: motionEase }}
            className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-50 w-max max-w-64 -translate-x-1/2 rounded-[6px] border border-border-lit bg-[#171a20] px-2.5 py-1.5 text-[11px] text-text shadow-xl"
          >
            {content}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}
