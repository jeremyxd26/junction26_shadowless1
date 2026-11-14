import { useId, useState } from 'react'
import type { Estimate } from '../api/types.ts'
import { estimateParts } from '../lib/estimate.ts'
import { estimateStrings } from '../lib/estimateStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { NumberChip } from './NumberChip.tsx'

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

/**
 * The estimate's text as a full-width box, for cards that use the badge's controlled mode. Since
 * contract 0.3.6 it also lists what the estimate is built from ("Based on", the observed Numbers,
 * each a chip that opens its evidence) and what it assumes ("We assume", each assumption's text
 * with its value). Without those fields (an older API) it shows only the text, as before (#504).
 */
export function EstimateNote({ estimate, id, onHero = false }: { estimate: Estimate; id: string; onHero?: boolean }) {
  const { lang } = useSettings()
  const s = estimateStrings(lang)
  const { observed, assumptions } = estimateParts(estimate)
  const box = onHero ? 'bg-on-hero/10 text-on-hero' : 'bg-estimate-tint text-ink-2'
  const heading = `font-semibold ${onHero ? 'text-on-hero' : 'text-ink'}`
  const muted = onHero ? 'text-on-hero-muted' : ''
  const tone = onHero ? 'hero' : 'mint'
  return (
    <div id={id} className={`mt-2 rounded-md p-3 text-sm ${box}`}>
      <p className={`font-semibold ${onHero ? 'text-on-hero' : 'text-estimate'}`}>
        <span aria-hidden="true">≈ </span>
        {estimate.label}
      </p>
      <p className={`mt-1 ${muted}`}>{estimate.text}</p>

      {observed.length > 0 && (
        <section className="mt-3">
          <h4 className={heading}>{s.basedOn}</h4>
          <ul className="mt-1 flex flex-col gap-1">
            {observed.map((number, index) => (
              <li key={number.evidence_ref ?? `${number.method}-${index}`} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className={`min-w-0 flex-1 basis-0 ${muted}`}>{number.label}</span>
                <NumberChip number={number} tone={tone} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {assumptions.length > 0 && (
        <section className="mt-3">
          <h4 className={heading}>{s.weAssume}</h4>
          <ul className="mt-1 flex flex-col gap-1">
            {assumptions.map((assumption, index) => (
              <li key={`${assumption.code}-${index}`} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className={`min-w-0 flex-1 basis-0 ${muted}`}>{assumption.text}</span>
                {/* A `user_input@1` value has no evidence ref, so NumberChip draws a plain chip, not a button. */}
                {assumption.value && <NumberChip number={assumption.value} tone={tone} />}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
