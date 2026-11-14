// The numbers a review answer moves on the opening (#317), kept pure so it runs in Node tests.
import type { BasketKey, LabelChange, LabelResponse } from '../api/types.ts'
import type { NumberMotion } from '../components/cards.tsx'
import { BASKETS } from './baskets.ts'

/** Keys whose "was …" hint is shown: the hero, its reserve and the basket the purchase moved to. */
const HINTED = new Set(['safe_to_spend', 'irregular_reserve', 'regular_essentials', 'unexpected_necessities', 'everyday_spending'])

/**
 * The numbers the answer changed: `changes[]` only. They drive the hero, the counters and the
 * overlay. `effect` (contract 0.3.2) is the confirmation in Sentti's reply: its text, and its items
 * list numbers that did not move too (safe to spend in "stays the same"), so they never reach here.
 */
export function answerChanges(response: LabelResponse): LabelChange[] {
  return response.changed ? response.changes : []
}

/**
 * How the opening's numbers move after a label response: counters from each `before`, "was …"
 * hints and the tinted row after an answer, and "stays the same" when safe to spend did not move.
 * `flies`: the amount flies into Sentti's reply, so basket rows wait for it to leave.
 */
export function answerMotion(
  changes: LabelChange[],
  answered: boolean,
  basket: BasketKey,
  flies: boolean,
  run: number,
): NumberMotion & { seq: number } {
  return {
    seq: run,
    counts: Object.fromEntries(
      changes.map((change) => [
        change.key,
        // Basket rows start counting when the amount leaves the waiting row.
        { seq: run, from: change.before, run: !flies || !(change.key in BASKETS) },
      ]),
    ),
    was: answered
      ? Object.fromEntries(changes.filter((change) => HINTED.has(change.key)).map((change) => [change.key, change.before]))
      : {},
    steady: answered && changes.length > 0 && !changes.some((change) => change.key === 'safe_to_spend'),
    highlight: answered ? basket : null,
    waiting: flies ? 'keep' : null,
  }
}
