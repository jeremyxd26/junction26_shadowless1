import { useEffect, useId, useReducer, useRef, type ActionDispatch } from 'react'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { BasketKey, ReviewCard } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { useOpening } from '../lib/openingContext.ts'
import {
  reviewPlacement,
  threadReview,
  THREAD_REVIEW_START,
  type ThreadReview,
  type ThreadReviewEvent,
} from '../lib/reviewPointer.ts'
import { reviewStrings } from '../lib/reviewStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { ReviewAnswered, ReviewAsking } from './ReviewCard.tsx'

/**
 * A `review` card inside an answer (#318, #450). The question about a purchase is shown once:
 * - when the opening (or an earlier turn) shows it, this answer only points there: one line and a
 *   44 px "Show" button that scrolls to that card, which is on the screen whenever this shows;
 * - otherwise this answer shows the review card itself, with working answer buttons;
 * - once that card is closed (Not sure, or the review is gone), this answer shows nothing more: it
 *   does not turn into a pointer to the card a later answer then shows.
 * The card's state lives here, so it outlives the card itself.
 */
export function ReviewPointer({ card }: { card: ReviewCard }) {
  const opening = useOpening()
  const owner = useId()
  const [state, dispatch] = useReducer(threadReview, THREAD_REVIEW_START)
  const placement = reviewPlacement(card.tx_ref, owner, opening, state.kind === 'not_sure')
  if (placement === 'none') return null
  if (placement === 'pointer') return <Pointer card={card} />
  return <ThreadReviewCard card={card} owner={owner} state={state} dispatch={dispatch} />
}

function Pointer({ card }: { card: ReviewCard }) {
  const { lang } = useSettings()
  const s = reviewStrings(lang)
  const opening = useOpening()
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
      {opening && (
        <button
          type="button"
          onClick={() => opening.scrollToReview(card.tx_ref)}
          aria-label={s.showLabel}
          className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
        >
          {s.show}
        </button>
      )}
    </div>
  )
}

/**
 * The review card answered inside the thread: the same card and answer as in the opening, without
 * the opening's toast, undo and flight. After an answer the overview is refetched in the background.
 */
function ThreadReviewCard({
  card,
  owner,
  state,
  dispatch,
}: {
  card: ReviewCard
  owner: string
  state: ThreadReview
  dispatch: ActionDispatch<[ThreadReviewEvent]>
}) {
  const { lang, t, customerId } = useSettings()
  const opening = useOpening()
  const lastBasket = useRef<BasketKey | null>(null)
  const claim = opening?.claimThreadReview
  const release = opening?.releaseThreadReview

  // While this card is on the screen, later answers about the same purchase point here. Closing it
  // unmounts it (ReviewPointer renders nothing), which releases the purchase for a later answer.
  useEffect(() => {
    if (!claim || !release) return
    claim(card.tx_ref, owner)
    return () => release(card.tx_ref, owner)
  }, [claim, release, card.tx_ref, owner])

  async function send(basket: BasketKey) {
    if (!customerId || state.kind !== 'asking' || state.busy !== null) return
    lastBasket.current = basket
    dispatch({ type: 'send', basket })
    try {
      await api.label({ customer_id: customerId, tx_ref: card.tx_ref, basket, language: lang })
      dispatch({ type: 'saved', basket })
      opening?.refresh()
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'tx_ref_not_found') {
        dispatch({ type: 'gone' })
        return
      }
      const wait = caught instanceof ApiError ? caught.retryAfter : null
      dispatch({
        type: 'failed',
        error: {
          message: caught instanceof ApiError ? caught.message : t.reviewSaveFailed,
          retryable: caught instanceof ApiError ? caught.retryable : true,
          until: wait ? Date.now() + wait * 1000 : null,
        },
      })
    }
  }

  if (state.kind === 'answered') return <ReviewAnswered card={card} basket={state.basket} />
  if (state.kind === 'not_sure') return null
  return (
    <ReviewAsking
      card={card}
      busy={state.busy}
      error={state.error}
      leaving={false}
      onAnswer={(basket) => void send(basket)}
      onNotSure={() => dispatch({ type: 'not_sure' })}
      onRetry={() => {
        if (lastBasket.current) void send(lastBasket.current)
      }}
    />
  )
}
