import { useId, useState } from 'react'
import type { Estimate, Num } from '../api/types.ts'
import { estimateParts, estimateReceipt } from '../lib/estimate.ts'
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
export function EstimateNote({
  estimate,
  id,
  onHero = false,
  result,
}: {
  estimate: Estimate
  id: string
  onHero?: boolean
  /**
   * The hero's own amount: with it, a safe-to-spend estimate is a short receipt (Renat's phone test): one plain
   * line, the balance and what is set aside as plain right-aligned text, the result, and the method and assumptions
   * folded under "How we estimate" (closed). Every value is the API's display.
   */
  result?: Num
}) {
  const { lang } = useSettings()
  const s = estimateStrings(lang)
  const { observed, assumptions } = estimateParts(estimate)
  const receipt = result ? estimateReceipt(estimate) : null
  const box = onHero ? 'bg-on-hero/10 text-on-hero' : 'bg-estimate-tint text-ink-2'
  const heading = `font-semibold ${onHero ? 'text-on-hero' : 'text-ink'}`
  const muted = onHero ? 'text-on-hero-muted' : ''
  const tone = onHero ? 'hero' : 'mint'
  const parts = (
    <>
      {observed.length > 0 && (
        <section className="mt-3">
          <h4 className={heading}>{s.basedOn}</h4>
          <ul className="mt-1 flex flex-col gap-1">
            {observed.map((number, index) => (
              <li key={number.evidence_ref ?? `${number.method}-${index}`} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className={`min-w-[min(6rem,100%)] flex-1 basis-0 break-words ${muted}`}>{number.label}</span>
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
                <span className={`min-w-[min(6rem,100%)] flex-1 basis-0 break-words ${muted}`}>{assumption.text}</span>
                {/* A `user_input@1` value has no evidence ref, so NumberChip draws a plain chip, not a button. */}
                {assumption.value && <NumberChip number={assumption.value} tone={tone} />}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
  if (receipt && result) {
    return (
      <div id={id} className={`mt-2 rounded-md p-3 text-sm ${box}`}>
        <p className={heading}>{s.plain}</p>
        <dl className="mt-2 flex flex-col gap-1 tabular-nums">
          {receipt.map(({ key, number }, index) => (
            <div key={key} className="flex items-baseline justify-between gap-3">
              <dt className={`min-w-0 break-words ${muted}`}>
                {index > 0 ? '− ' : ''}
                {s.receipt[key]}
              </dt>
              <dd className="shrink-0 text-right">{number.display}</dd>
            </div>
          ))}
          <div className={`mt-1 flex items-baseline justify-between gap-3 border-t pt-2 ${onHero ? 'border-on-hero/30' : 'border-line'}`}>
            <dt className={`min-w-0 break-words ${muted}`}>{s.spread}</dt>
            <dd className={`shrink-0 text-right text-base ${heading}`}>{result.display}</dd>
          </div>
        </dl>
        <details className="group mt-1">
          <summary
            className={`inline-flex min-h-11 cursor-pointer list-none items-center gap-1 font-semibold [&::-webkit-details-marker]:hidden ${
              onHero ? 'text-on-hero' : 'text-brand'
            }`}
          >
            {s.howWeEstimate}
            <span aria-hidden="true" className="transition-transform group-open:rotate-90">
              ›
            </span>
          </summary>
          <p className={muted}>{estimate.text}</p>
          {parts}
        </details>
      </div>
    )
  }
  return (
    <div id={id} className={`mt-2 rounded-md p-3 text-sm ${box}`}>
      <p className={`font-semibold ${onHero ? 'text-on-hero' : 'text-estimate'}`}>
        <span aria-hidden="true">≈ </span>
        {estimate.label}
      </p>
      <p className={`mt-1 ${muted}`}>{estimate.text}</p>
      {parts}
    </div>
  )
}
