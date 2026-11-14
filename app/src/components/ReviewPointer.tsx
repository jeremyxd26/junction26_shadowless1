import { useEffect, useRef } from 'react'
import type { ReviewCard } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { useOpening } from '../lib/openingContext.ts'
import { pointerState } from '../lib/reviewPointer.ts'
import { reviewStrings } from '../lib/reviewStrings.ts'
import { useSettings } from '../lib/settings.ts'

/**
 * A `review` card inside an answer (#318). The question about a pending purchase lives once, in
 * Sentti's opening turn, so an answer never shows a second live question. Instead: one short line,
 * "Sentti already asked about this purchase.", with a 44 px "Show" button that scrolls to the
 * question card. When the answer created the review after the overview loaded, the overview is
 * refetched once first. No text here says the question was answered.
 */
export function ReviewPointer({ card }: { card: ReviewCard }) {
  const { lang } = useSettings()
  const s = reviewStrings(lang)
  const opening = useOpening()
  const state = pointerState(card.tx_ref, opening)
  // A review the opening does not know yet was created by this answer: refetch the overview once,
  // so the opening asks about it and this pointer gets its button.
  const refreshed = useRef(false)
  useEffect(() => {
    if (state !== 'elsewhere' || !opening || refreshed.current) return
    refreshed.current = true
    opening.refresh()
  }, [state, opening])

  const look = BASKETS.unclassified
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-surface px-4 py-2">
      <span
        aria-hidden="true"
        className={`inline-flex size-8 shrink-0 items-center justify-center rounded-md text-sm font-bold ${look.tint} ${look.color}`}
      >
        {look.icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink">{s.asked}</p>
        {card.subtitle && <p className="text-xs text-muted">{card.subtitle}</p>}
      </div>
      {state === 'asking' && opening && (
        <button
          type="button"
          onClick={opening.scrollToReview}
          aria-label={s.showLabel}
          className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
        >
          {s.show}
        </button>
      )}
    </div>
  )
}
