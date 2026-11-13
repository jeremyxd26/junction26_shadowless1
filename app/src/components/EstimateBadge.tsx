import { useId, useState } from 'react'
import type { Estimate } from '../api/types.ts'

/**
 * Shows the API's estimate label as a dashed, neutral pill; tapping it reveals the assumption
 * in plain words. `onHero` draws it white with an on-hero-muted dashed border (DESIGN.md).
 */
export function EstimateBadge({ estimate, onHero = false }: { estimate: Estimate; onHero?: boolean }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const pill = onHero
    ? 'border-on-hero-muted text-on-hero'
    : 'border-estimate bg-estimate-tint text-estimate'
  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex min-h-11 items-center"
      >
        <span className={`inline-flex items-center gap-1 rounded-pill border border-dashed px-2.5 py-1 text-xs font-semibold ${pill}`}>
          <span aria-hidden="true">≈</span>
          {estimate.label}
        </span>
      </button>
      {open && (
        <p id={id} className={`mt-1 text-right text-sm ${onHero ? 'text-on-hero-muted' : 'text-muted'}`}>
          {estimate.text}
        </p>
      )}
    </div>
  )
}
