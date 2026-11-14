import { useId } from 'react'
import type { BreakdownCard } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { stripItems } from '../lib/basketStrip.ts'
import type { NumberMotion } from './cards.tsx'
import { NumberChip } from './NumberChip.tsx'

export interface BasketStripProps {
  /** The baskets breakdown, as the API sends it. */
  card: BreakdownCard
  /** The #35 counters, "was" hints and highlight, only where the flight plays. */
  motion?: NumberMotion
  /** Only these basket keys, in the card's order (e.g. the mini row of a review answer: the
   *  waiting cell and the chosen basket). All baskets when left out. */
  keys?: readonly string[]
  /** The heading: the card's API `title` by default; `null` hides it (the section keeps it as its
   *  accessible name). */
  title?: string | null
  /** This strip carries the review flight's targets: `#baskets-title`, `[data-amount-key]` and
   *  one `li` per cell. Exactly one strip on the page may set it, so the flight finds one target. */
  flight?: boolean
}

/**
 * The basket strip: a heading and a 2-column list of cells, each icon + label + colour and the
 * amount as a number chip. Used in three places (#312): Sentti's short answer after a review
 * answer (a mini row the amount flies into, `flight`), the answer to "Where did my money go?", and
 * the overview sheet (#320). Labels wrap and are never truncated. The strip is not a button and has
 * no tap target of its own; an amount chip opens its evidence like everywhere else.
 */
export function BasketStrip({ card, motion, keys, title, flight = false }: BasketStripProps) {
  const items = stripItems(card, { keys, waiting: motion?.waiting ?? null })
  const heading = title === undefined ? card.title : title
  const ownId = useId()
  // The flight focuses `#baskets-title`: the heading, or the section itself when it has none.
  const headingId = flight ? 'baskets-title' : ownId
  return (
    <section
      id={heading === null && flight ? 'baskets-title' : undefined}
      tabIndex={heading === null && flight ? -1 : undefined}
      aria-labelledby={heading !== null ? headingId : undefined}
      aria-label={heading === null ? card.title : undefined}
      className="outline-none"
    >
      {heading !== null && (
        <h2 id={headingId} tabIndex={flight ? -1 : undefined} className="mb-2 text-base leading-5 font-semibold text-ink outline-none">
          {heading}
        </h2>
      )}
      <ul className="grid grid-cols-2 gap-x-3 gap-y-2">
        {items.map((item) => {
          const look = BASKETS[item.key]
          const highlighted = motion?.highlight === item.key
          const leaving = item.key === 'unclassified' && motion?.waiting === 'leave'
          return (
            <li
              key={item.key}
              data-basket-row={flight ? item.key : undefined}
              className={`-mx-1 flex min-w-0 flex-col items-start rounded-md px-1 transition-colors duration-500 ${
                highlighted ? look.tint.split(' ')[0] : ''
              } ${leaving ? 'row-leave' : item.key === 'unclassified' ? 'row-enter' : ''}`}
            >
              <p className={`flex min-w-0 items-start gap-1.5 text-sm leading-5 font-semibold ${look.color}`}>
                <span
                  aria-hidden="true"
                  className={`inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-xs font-bold ${look.tint}`}
                >
                  {look.icon}
                </span>
                <span className="min-w-0 break-words">{item.label}</span>
              </p>
              <span data-amount-key={flight ? item.key : undefined} className="max-w-full">
                <NumberChip number={item.amount} size="inline" count={motion?.counts[item.key]} />
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
