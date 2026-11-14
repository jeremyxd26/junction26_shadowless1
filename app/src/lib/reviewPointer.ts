// What a `review` card in an answer shows (#318, #450), kept pure so it runs in Node tests.
import type { BasketKey } from '../api/types.ts'
import type { ReviewError } from '../components/ReviewCard.tsx'
import type { Opening } from './openingContext.ts'

/**
 * - `pointer`: the opening shows the question about this purchase (asking or answered), or an
 *   earlier turn in the thread shows it: one line and a "Show" button that scrolls to that card.
 * - `card`: nobody shows it (Not sure, another purchase, no question in the opening, or outside
 *   the thread): this answer shows the review card itself, with its answer buttons.
 */
export type ReviewPlacement = 'pointer' | 'card'

export function reviewPlacement(txRef: string, owner: string, opening: Opening | null): ReviewPlacement {
  if (!opening) return 'card'
  if (opening.shownReview?.txRef === txRef) return 'pointer'
  const holder = opening.threadReviews[txRef]
  return holder && holder !== owner ? 'pointer' : 'card'
}

/** The review card inside an answer: asking (maybe sending or failed), answered, or closed. */
export type ThreadReview =
  | { kind: 'asking'; busy: BasketKey | null; error: ReviewError | null }
  | { kind: 'answered'; basket: BasketKey }
  | { kind: 'not_sure' }

export type ThreadReviewEvent =
  | { type: 'send'; basket: BasketKey }
  | { type: 'saved'; basket: BasketKey }
  | { type: 'failed'; error: ReviewError }
  | { type: 'gone' }
  | { type: 'not_sure' }

export const THREAD_REVIEW_START: ThreadReview = { kind: 'asking', busy: null, error: null }

export function threadReview(state: ThreadReview, event: ThreadReviewEvent): ThreadReview {
  switch (event.type) {
    case 'send':
      return state.kind === 'asking' && state.busy === null ? { kind: 'asking', busy: event.basket, error: null } : state
    case 'saved':
      return { kind: 'answered', basket: event.basket }
    case 'failed':
      return state.kind === 'asking' ? { kind: 'asking', busy: null, error: event.error } : state
    // The review is no longer open (expired or answered elsewhere): the card goes, like Not sure.
    case 'gone':
      return { kind: 'not_sure' }
    // Not sure closes the card, but not while an answer is being sent.
    case 'not_sure':
      return state.kind === 'asking' && state.busy === null ? { kind: 'not_sure' } : state
  }
}
