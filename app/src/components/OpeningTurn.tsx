// Sentti's opening turn: turn 0 of the thread on `/` (DESIGN.md "Thread", "Opening turn").
// One thought per screen (#310): greeting, the big safe-to-spend card, "Sentti asks" and 2–3
// questions; no speaker line here, the header carries the AI tag.
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from '../api/errors.ts'
import type { OverviewResponse } from '../api/types.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { prefersReducedMotion } from '../lib/motion.ts'
import { OpeningContext, type AnsweredReview, type Opening, type ShownReview } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import type { ClientTurnRequest } from '../lib/thread.ts'
import { notifyAsked } from '../lib/threadEvents.ts'
import type { ChatSession } from '../lib/useChat.ts'
import type { Loaded } from '../lib/useLoad.ts'
import { Overview } from '../screens/Overview.tsx'
import { ErrorBlock, LoadingBlock } from './States.tsx'

const noop = () => {}

/** The same card in the same state (and, once answered, the same basket): nothing to re-render. */
function sameReview(a: ShownReview | null, b: ShownReview | null): boolean {
  if (!a || !b) return a === b
  if (a.txRef !== b.txRef || a.phase !== b.phase) return false
  return a.phase === 'asking' || (b.phase === 'answered' && a.basketKey === b.basketKey && a.basketLabel === b.basketLabel)
}

/** The review card for `txRef`: the opening's first, else the one a thread turn shows (#450). */
function scrollToReview(txRef: string) {
  const selector = `[data-review-card="${CSS.escape(txRef)}"]`
  const card =
    document.querySelector<HTMLElement>(`[data-turn="opening"] ${selector}`) ?? document.querySelector<HTMLElement>(selector)
  if (!card) return
  card.scrollIntoView({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  card.focus({ preventScroll: true })
}

/** A turn already in the thread, brought back to the top (a second tap on a client turn's chip). */
function scrollToTurn(turnId: number) {
  document
    .querySelector(`[data-turn="${turnId}"]`)
    ?.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
}

interface ProviderProps {
  overview: Loaded<OverviewResponse>
  /** The chat's own push; the opening's chips reach the thread through it (#319). */
  pushClientTurn: ChatSession['pushClientTurn']
  children: ReactNode
}

/**
 * Gives the whole thread what the opening offers (`useOpening()`): answer cards are later turns,
 * not children of the opening, so the value sits above the thread.
 */
export function OpeningProvider({ overview, pushClientTurn, children }: ProviderProps) {
  const data = overview.status === 'ready' ? overview.data : null
  const refresh = overview.status === 'ready' ? overview.refresh : noop
  const reviewTxRef = data?.reviews[0]?.tx_ref ?? null
  const [shownReview, setShownReview] = useState<ShownReview | null>(null)
  const [threadReviews, setThreadReviews] = useState<Record<string, string>>({})
  const reportReview = useCallback(
    (next: ShownReview | null) => setShownReview((current) => (sameReview(current, next) ? current : next)),
    [],
  )
  const answered = useMemo<AnsweredReview | null>(
    () =>
      shownReview?.phase === 'answered'
        ? { txRef: shownReview.txRef, basketKey: shownReview.basketKey, basketLabel: shownReview.basketLabel }
        : null,
    [shownReview],
  )
  const claimThreadReview = useCallback(
    (txRef: string, owner: string) => setThreadReviews((current) => (current[txRef] ? current : { ...current, [txRef]: owner })),
    [],
  )
  const releaseThreadReview = useCallback(
    (txRef: string, owner: string) =>
      setThreadReviews((current) => {
        if (current[txRef] !== owner) return current
        const next = { ...current }
        delete next[txRef]
        return next
      }),
    [],
  )
  // A client turn moves the thread on like a question does, so the opening's Undo toast closes.
  const pushTurn = useCallback(
    (request: ClientTurnRequest) => {
      notifyAsked()
      const pushed = pushClientTurn(request)
      if (pushed?.existed) scrollToTurn(pushed.id)
    },
    [pushClientTurn],
  )
  const value = useMemo<Opening>(
    () => ({
      reviewTxRef,
      overview: data,
      shownReview,
      reportReview,
      answered,
      threadReviews,
      claimThreadReview,
      releaseThreadReview,
      refresh,
      scrollToReview,
      pushClientTurn: pushTurn,
    }),
    [reviewTxRef, data, shownReview, reportReview, answered, threadReviews, claimThreadReview, releaseThreadReview, refresh, pushTurn],
  )
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
