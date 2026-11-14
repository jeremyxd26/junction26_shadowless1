import { useEffect, useId, useState, type ReactNode } from 'react'
import { UNFOLD_OPENING } from '../lib/openingFold.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'

/**
 * The opening after the customer's first message: one compact line at the top of the thread
 * ("Left to spend €97.46 · 1 question from Sentti ›"), the amount as the API's own `display`, the
 * question count only while the review is pending. A tap shows the whole opening in place, a second
 * tap folds it. The opening stays mounted while folded (`hidden`), so its review state and timers
 * live on. Each new turn folds it again; an empty thread (New chat) shows it whole.
 */
export function OpeningFold({ canFold, foldKey, children }: { canFold: boolean; foldKey: number | undefined; children: ReactNode }) {
  const { t } = useSettings()
  const opening = useOpening()
  const id = useId()
  // Open for one turn: the latest turn's id when the customer unfolded it; a newer turn folds it again.
  const [openFor, setOpenFor] = useState<number | undefined | null>(null)
  const expanded = !canFold || openFor === foldKey

  // "Bring the review card into view" from an answer (#450) unfolds the opening first.
  useEffect(() => {
    const unfold = () => setOpenFor(foldKey)
    window.addEventListener(UNFOLD_OPENING, unfold)
    return () => window.removeEventListener(UNFOLD_OPENING, unfold)
  }, [foldKey])

  const display = opening?.overview?.hero?.primary.display
  const asking = opening?.shownReview?.phase === 'asking'
  return (
    <>
      {canFold && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => setOpenFor(expanded ? null : foldKey)}
          className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-left text-sm leading-5 text-ink hover:bg-sunken"
        >
          <span className="min-w-0 flex-1">
            <span className="font-semibold">{display ? t.foldLeft(display) : t.overview}</span>
            {asking && <span className="text-ink-2"> · {t.foldQuestions(1)}</span>}
          </span>
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '-rotate-90' : 'rotate-90'}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      <div id={id} hidden={!expanded} className={canFold && expanded ? 'card-enter' : undefined}>
        {children}
      </div>
    </>
  )
}
