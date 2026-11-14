// Sentti's opening turn: turn 0 of the thread on `/` (DESIGN.md "Thread", "Opening turn").
// In this step it shows the overview as it is; the compact opening template comes later.
import { useMemo, type ReactNode } from 'react'
import { ApiError } from '../api/errors.ts'
import type { OverviewResponse } from '../api/types.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { prefersReducedMotion } from '../lib/motion.ts'
import { OpeningContext, type Opening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import type { Loaded } from '../lib/useLoad.ts'
import { Overview } from '../screens/Overview.tsx'
import { SenttiLabel } from './AnswerView.tsx'
import { ErrorBlock, LoadingBlock } from './States.tsx'

const noop = () => {}

function scrollToReview() {
  const card = document.querySelector<HTMLElement>('[data-review-card]')
  if (!card) return
  card.scrollIntoView({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  card.focus({ preventScroll: true })
}

/**
 * Gives the whole thread what the opening offers (`useOpening()`): answer cards are later turns,
 * not children of the opening, so the value sits above the thread.
 */
export function OpeningProvider({ overview, children }: { overview: Loaded<OverviewResponse>; children: ReactNode }) {
  const data = overview.status === 'ready' ? overview.data : null
  const refresh = overview.status === 'ready' ? overview.refresh : noop
  const reviewTxRef = data?.reviews[0]?.tx_ref ?? null
  const value = useMemo<Opening>(() => ({ reviewTxRef, refresh, scrollToReview }), [reviewTxRef, refresh])
  return <OpeningContext.Provider value={value}>{children}</OpeningContext.Provider>
}

interface Props {
  overview: Loaded<OverviewResponse>
  /** The persona list; when it fails there is no customer to open with. */
  personas: Loaded<unknown>
  onSwitchPersona: () => void
}

/**
 * The overview inside the thread. App mounts it with `key={customerId}`, so a persona switch gives
 * a fresh opening, while one `Overview` instance lives for the persona's session: the review state,
 * its timers and the overlay are kept in it, and a background refresh keeps it mounted.
 */
export function OpeningTurn({ overview, personas, onSwitchPersona }: Props) {
  const { lang, t } = useSettings()
  const s = chatStrings(lang)
  const failed = overview.status === 'error' ? overview : personas.status === 'error' ? personas : null

  return (
    <section data-turn="opening" aria-label={s.sentti} className="flex flex-col gap-3">
      <SenttiLabel s={s} />
      {overview.status === 'ready' ? (
        <Overview overview={overview.data} onRefresh={overview.refresh} />
      ) : failed ? (
        <ErrorBlock message={errorMessage(failed.error)} onRetry={retryFor(failed)}>
          <button
            type="button"
            onClick={onSwitchPersona}
            className="min-h-11 rounded-pill border border-mint-line bg-surface px-5 font-semibold text-brand"
          >
            {t.switchPersona}
          </button>
        </ErrorBlock>
      ) : (
        <LoadingBlock lines={6} />
      )}
    </section>
  )
}

function errorMessage(error: unknown): string | undefined {
  return error instanceof ApiError ? error.message : undefined
}

/** Offer a retry only when the API says it may help (contract section 4). */
function retryFor(result: Loaded<unknown>): (() => void) | undefined {
  if (result.status !== 'error') return undefined
  if (result.error instanceof ApiError && !result.error.retryable) return undefined
  return result.retry
}
