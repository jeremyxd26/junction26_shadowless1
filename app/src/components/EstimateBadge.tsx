import { useId, useState } from 'react'
import type { Estimate } from '../api/types.ts'

interface Props {
  estimate: Estimate
  onHero?: boolean
  /**
   * Controlled mode: the card shows `estimate.text` itself (for example full width under its
   * header) and passes the state and the id of that text here. Without it, the badge shows
   * the text under itself.
   */
  control?: { open: boolean; onToggle: () => void; textId: string }
}

/**
 * Shows the API's estimate label as a dashed, neutral pill; tapping it reveals the assumption
 * in plain words. `onHero` draws it white with an on-hero-muted dashed border (DESIGN.md).
 */
export function EstimateBadge({ estimate, onHero = false, control }: Props) {
  const [ownOpen, setOwnOpen] = useState(false)
  const ownId = useId()
  const open = control ? control.open : ownOpen
  const id = control ? control.textId : ownId
  const pill = onHero
    ? 'border-on-hero-muted text-on-hero'
    : 'border-estimate bg-estimate-tint text-estimate'
  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => (control ? control.onToggle() : setOwnOpen((value) => !value))}
        className="inline-flex min-h-11 items-center"
      >
        <span className={`inline-flex items-center gap-1 rounded-pill border border-dashed px-2.5 py-1 text-xs font-semibold ${pill}`}>
          <span aria-hidden="true">≈</span>
          {estimate.label}
        </span>
      </button>
      {!control && open && (
        <p id={id} className={`mt-1 text-right text-sm ${onHero ? 'text-on-hero-muted' : 'text-muted'}`}>
          {estimate.text}
        </p>
      )}
    </div>
  )
}

/** The estimate's text as a full-width box, for cards that use the badge's controlled mode. */
export function EstimateNote({ estimate, id, onHero = false }: { estimate: Estimate; id: string; onHero?: boolean }) {
  const box = onHero ? 'bg-on-hero/10 text-on-hero' : 'bg-estimate-tint text-ink-2'
  return (
    <div id={id} className={`mt-2 rounded-md p-3 text-sm ${box}`}>
      <p className={`font-semibold ${onHero ? 'text-on-hero' : 'text-estimate'}`}>
        <span aria-hidden="true">≈ </span>
        {estimate.label}
      </p>
      <p className={`mt-1 ${onHero ? 'text-on-hero-muted' : ''}`}>{estimate.text}</p>
    </div>
  )
}
