import { createContext, useContext } from 'react'

/**
 * What Sentti's opening turn offers to the rest of the thread, for example an answer card that
 * points back to the "Sentti asks" question.
 */
export interface Opening {
  /** The `tx_ref` of the review the opening asks about, or null when none is pending. */
  reviewTxRef: string | null
  /** Refetch the overview in the background (the opening stays on screen). */
  refresh: () => void
  /** Bring the "Sentti asks" card into view and move focus to it. */
  scrollToReview: () => void
}

export const OpeningContext = createContext<Opening | null>(null)

/** The opening of the thread, or null outside it (for example on `/cards`). */
export function useOpening(): Opening | null {
  return useContext(OpeningContext)
}
