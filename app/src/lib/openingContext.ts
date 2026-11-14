import { createContext, useContext } from 'react'
import type { BasketKey, OverviewResponse } from '../api/types.ts'
import type { ClientTurnRequest } from './thread.ts'

/**
 * The "Sentti asks" card the opening shows right now, as the overview reports it (#450). Once it is
 * answered, it also names the basket, with the label the label response gave (#452).
 */
export type ShownReview =
  | { txRef: string; phase: 'asking' }
  | { txRef: string; phase: 'answered'; basketKey: BasketKey; basketLabel: string }

/** The opening's question, answered (Needed or My choice) and not undone (#452). */
export interface AnsweredReview {
  txRef: string
  basketKey: BasketKey
  basketLabel: string
}

/**
 * What Sentti's opening turn offers to the rest of the thread, for example an answer card that
 * points back to the "Sentti asks" question.
 */
export interface Opening {
  /** The `tx_ref` of the review the opening asks about, or null when none is pending. */
  reviewTxRef: string | null
  /** The overview the opening shows, once loaded (null while it loads or failed), for client turns (#703). */
  overview: OverviewResponse | null
  /** The review card the opening actually shows (asking or answered), or null (Not sure, none). */
  shownReview: ShownReview | null
  /** The overview reports the card it shows; null when it shows none. */
  reportReview: (shown: ShownReview | null) => void
  /** The opening's question once answered, with its basket; null while asking, after Undo, or none. */
  answered: AnsweredReview | null
  /** Review cards answered inside the thread (#450), by `tx_ref`: the turn that shows it. */
  threadReviews: Record<string, string>
  /** A thread turn shows the review card for `txRef`; the first one keeps it until it releases it. */
  claimThreadReview: (txRef: string, owner: string) => void
  releaseThreadReview: (txRef: string, owner: string) => void
  /** Refetch the overview in the background (the opening stays on screen). */
  refresh: () => void
  /** Bring the review card for `txRef` into view (the opening's first) and move focus to it. */
  scrollToReview: (txRef: string) => void
  /**
   * Push a client turn into the thread (#319), for an opening chip: nothing is sent to the API.
   * A second push with the same `id` brings the first turn back into view instead.
   */
  pushClientTurn: (request: ClientTurnRequest) => void
}

export const OpeningContext = createContext<Opening | null>(null)

/** The opening of the thread, or null outside it (for example on `/cards`). */
export function useOpening(): Opening | null {
  return useContext(OpeningContext)
}
