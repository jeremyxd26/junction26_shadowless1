import { useId, useState } from 'react'
import type { Estimate } from '../api/types.ts'

/** Shows the API's estimate label; tapping it reveals the assumption in plain words. */
export function EstimateBadge({ estimate }: { estimate: Estimate }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex min-h-11 items-center"
      >
        <span className="inline-flex items-center gap-1 rounded-pill bg-estimate-tint px-2.5 py-1 text-xs font-semibold text-estimate">
          <span aria-hidden="true">≈</span>
          {estimate.label}
        </span>
      </button>
      {open && (
        <p id={id} className="mt-1 text-right text-sm text-muted">
          {estimate.text}
        </p>
      )}
    </div>
  )
}
