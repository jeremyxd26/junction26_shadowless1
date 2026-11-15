import type { BreakdownCard } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { askInThread } from '../lib/url.ts'

const KEYS = ['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified']

/** Short names for the one-line legend; the API's own labels name the baskets in the accessible summary. */
const SHORT: Record<string, { en: string; fi: string }> = {
  regular_essentials: { en: 'Regular', fi: 'Säännölliset' },
  unexpected_necessities: { en: 'Unexpected', fi: 'Yllättävät' },
  everyday_spending: { en: 'Everyday', fi: 'Arki' },
}

/**
 * The three baskets at a glance on the opening (Renat, #945): one slim bar in the basket colours, its segments as wide
 * as the API's shares, and a one-line legend with each basket's icon, short name and share display. A tap asks
 * "Where did my money go?". Never colour alone: icons, names and shares are in the legend. A purchase still waiting
 * for an answer is a hatched segment.
 */
export function BasketBar({ card }: { card: BreakdownCard }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const items = KEYS.map((key) => card.items.find((item) => item.key === key)).filter(
    (item): item is BreakdownCard['items'][number] => Boolean(item && item.share && item.share.value > 0),
  )
  if (items.length === 0) return null
  const named = items.filter((item) => SHORT[item.key])
  const summary = `${s.basketBarLabel}: ${items.map((item) => `${item.label} ${item.share?.display ?? ''}`).join(', ')}`
  return (
    <button
      type="button"
      data-opening-part="baskets"
      onClick={() => askInThread(s.openingFirst[0])}
      aria-label={`${summary}. ${s.openingFirst[0]}`}
      className="flex min-h-11 w-full flex-col justify-center gap-1 rounded-lg px-1 py-1 text-left hover:bg-sunken"
    >
      <span aria-hidden="true" className="flex h-2.5 w-full overflow-hidden rounded-pill bg-sunken">
        {items.map((item) => (
          <span
            key={item.key}
            className={`h-full ${BASKETS[item.key]?.bar ?? ''} transition-[width] duration-(--duration-money) motion-reduce:transition-none [&+&]:ml-0.5`}
            style={{ width: `${item.share?.value ?? 0}%` }}
          />
        ))}
      </span>
      <span aria-hidden="true" className="flex flex-wrap items-center justify-center gap-x-2.5 gap-y-0.5 text-xs text-ink-2">
        {named.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1">
            <span className={`inline-flex size-3.5 items-center justify-center ${BASKETS[item.key]?.color ?? ''}`}>{BASKETS[item.key]?.icon}</span>
            {SHORT[item.key][lang]} <span className="font-semibold text-ink tabular-nums">{item.share?.display}</span>
          </span>
        ))}
      </span>
    </button>
  )
}
