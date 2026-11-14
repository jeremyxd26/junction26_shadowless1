// Which cells a basket strip shows (components/BasketStrip.tsx), kept pure so it runs in Node tests.
import type { BreakdownCard } from '../api/types.ts'
import { BASKETS } from './baskets.ts'

type Item = BreakdownCard['items'][number]

/**
 * The breakdown items the strip shows, in the card's order:
 * - only the known baskets (`BASKETS`), and only `keys` when given;
 * - the waiting cell (`unclassified`) only while it has an amount, or while it counts to zero and
 *   fades out after an answer (`waiting` of the #35 motion), the same rule as `BasketsCard`.
 */
export function stripItems(
  card: BreakdownCard,
  { keys, waiting = null }: { keys?: readonly string[]; waiting?: 'keep' | 'leave' | null } = {},
): Item[] {
  return card.items.filter(
    (item) =>
      item.key in BASKETS &&
      (keys === undefined || keys.includes(item.key)) &&
      !(item.key === 'unclassified' && item.amount.value <= 0 && !waiting),
  )
}
