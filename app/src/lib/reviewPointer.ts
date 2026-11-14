// What a `review` card in an answer shows (#318), kept pure so it runs in Node tests.
import type { Opening } from './openingContext.ts'

/**
 * - `asking`: the opening asks about this purchase right now: point to it with a button.
 * - `elsewhere`: the opening does not ask about it (yet). Either the answer created the review
 *   after the overview loaded, so the overview is refetched once, or it was answered meanwhile.
 *   The line stays true in both cases, without a button.
 * - `outside`: no opening (for example `/cards`): only the line.
 */
export type PointerState = 'asking' | 'elsewhere' | 'outside'

export function pointerState(txRef: string, opening: Opening | null): PointerState {
  if (!opening) return 'outside'
  return opening.reviewTxRef === txRef ? 'asking' : 'elsewhere'
}
