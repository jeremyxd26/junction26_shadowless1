import { useState, type KeyboardEvent } from 'react'
import type { BreakdownCard } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { usePrefersReducedMotion } from '../lib/motion.ts'
import { useSettings } from '../lib/settings.ts'
import { askInThread } from '../lib/url.ts'

const KEYS = ['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified']
const STROKE: Record<string, string> = {
  regular_essentials: 'stroke-basket-essentials',
  unexpected_necessities: 'stroke-basket-unexpected',
  everyday_spending: 'stroke-basket-everyday',
  unclassified: 'stroke-waiting',
}
/** The question the core answers with a basket's categories (core/agent/rules.py BASKET_CONTENTS). */
const CONTENTS: Record<string, { en: string; fi: string }> = {
  regular_essentials: { en: 'What is in my regular essentials?', fi: 'Mitä säännöllisiin välttämättömiin menoihin kuuluu?' },
  unexpected_necessities: { en: 'What is in my unexpected necessities?', fi: 'Mitä odottamattomiin välttämättömiin menoihin kuuluu?' },
  everyday_spending: { en: 'What is in my everyday spending?', fi: 'Mitä arjen kulutukseen kuuluu?' },
}
/** A rate's words at the end of a display, shown small under the number in the centre (the display is not reworded). */
const RATE = [' a month', ' / kk', ' a week', ' / vk', ' a year', ' / v']

// The ring in a 100-unit box drawn at 176 px: about 18 px thick, 2 px gaps, square ends, from 12 o'clock clockwise.
const R = 40
const WIDTH = 10.5
const C = 2 * Math.PI * R
const GAP = 1.2

function splitRate(display: string): [string, string] {
  const rate = RATE.find((suffix) => display.endsWith(suffix))
  return rate ? [display.slice(0, -rate.length), rate.trim().replace(/^\/\s*/, '')] : [display, '']
}

/**
 * The three baskets as a donut card (Renat, #953): the basket colour tokens (the waiting part hatched), the largest
 * basket first from 12 o'clock clockwise, each arc as long as the API's share (the only arithmetic: a share in percent
 * turned into an arc length), the total's display in the centre, and a legend of 44 px rows with the basket icon, the
 * name, the amount and the share, so colour is never alone. A tap (or Enter) on a segment or a row selects that basket:
 * the others dim, the centre shows its amount and name, and a button asks what is in it; again resets. Segments sweep in
 * (500 ms, 80 ms apart); none under reduced motion.
 */
export function BasketDonut({ card }: { card: BreakdownCard }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const reduced = usePrefersReducedMotion()
  const [selected, setSelected] = useState<string | null>(null)
  const items = KEYS.map((key) => card.items.find((item) => item.key === key))
    .filter((item): item is BreakdownCard['items'][number] => Boolean(item && item.share && item.share.value > 0))
    .sort((a, b) => (b.share?.value ?? 0) - (a.share?.value ?? 0))
  if (items.length === 0) return null
  const summary = `${s.basketBarLabel}: ${items.map((item) => `${item.label} ${item.share?.display ?? ''}`).join(', ')}. ${card.total.label} ${card.total.display}`
  // Each arc starts where the ones before it end: the shares before it, summed (no state changes in render).
  const arcs = items.map((item) => ((item.share?.value ?? 0) / 100) * C)
  const segments = items.map((item, index) => ({
    item,
    length: Math.max(0.5, arcs[index] - GAP),
    offset: -arcs.slice(0, index).reduce((sum, arc) => sum + arc, 0),
  }))
  const active = items.find((item) => item.key === selected) ?? null
  const toggle = (key: string) => setSelected((current) => (current === key ? null : key))
  const onKey = (key: string) => (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      toggle(key)
    }
  }
  const [amount, rate] = splitRate(active ? active.amount.display : card.total.display)
  return (
    <div data-basket-donut="" className="mt-2 flex flex-col items-center gap-3">
      <div className="relative size-44 shrink-0">
        <svg viewBox="0 0 100 100" className="size-full -rotate-90" role="img" aria-label={summary}>
          <defs>
            <pattern id="donut-hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="3" height="3" className="fill-waiting-tint" />
              <rect width="1.2" height="3" className="fill-waiting" />
            </pattern>
          </defs>
          <circle cx="50" cy="50" r={R} fill="none" strokeWidth={WIDTH} className="stroke-sunken" />
          {segments.map(({ item, length, offset }, index) => (
            <circle
              key={item.key}
              cx="50"
              cy="50"
              r={R}
              fill="none"
              strokeWidth={WIDTH}
              strokeDasharray={`${length} ${C - length}`}
              strokeDashoffset={offset}
              stroke={item.key === 'unclassified' ? 'url(#donut-hatch)' : undefined}
              tabIndex={0}
              role="button"
              aria-label={`${item.label}: ${item.amount.display}, ${item.share?.display ?? ''}`}
              aria-pressed={selected === item.key}
              onClick={() => toggle(item.key)}
              onKeyDown={onKey(item.key)}
              style={reduced ? undefined : { animationDelay: `${index * 80}ms`, animationFillMode: 'both' }}
              className={`cursor-pointer outline-none transition-opacity duration-(--duration-fast) focus-visible:opacity-80 ${
                item.key === 'unclassified' ? '' : (STROKE[item.key] ?? 'stroke-line-strong')
              } ${selected && selected !== item.key ? 'opacity-35' : ''} ${reduced ? '' : 'donut-sweep'}`}
            />
          ))}
        </svg>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-8 text-center">
          <span className="text-xl leading-7 font-semibold text-ink tabular-nums">{amount}</span>
          {rate && <span className="text-xs leading-4 text-muted">{rate}</span>}
          {active && <span className="mt-0.5 text-xs leading-4 text-ink-2">{active.label}</span>}
        </div>
      </div>
      <ul className="flex w-full flex-col">
        {items.map((item) => {
          const look = BASKETS[item.key]
          const on = selected === item.key
          return (
            <li key={item.key} className="border-t border-line first:border-t-0">
              <button
                type="button"
                aria-pressed={on}
                onClick={() => toggle(item.key)}
                className={`flex min-h-11 w-full items-center gap-2 rounded-md py-1 pr-1 text-left transition-opacity duration-(--duration-fast) hover:bg-sunken ${
                  selected && !on ? 'opacity-35' : ''
                } ${on ? 'outline outline-1 outline-line-strong' : ''}`}
              >
                <span aria-hidden="true" className={`inline-flex size-7 shrink-0 items-center justify-center rounded-md ${look?.tint ?? ''} ${look?.color ?? ''}`}>
                  {look?.icon}
                </span>
                <span className="min-w-0 flex-1 text-sm text-ink">{item.label}</span>
                <span className="flex shrink-0 flex-col items-end">
                  <span className="text-sm font-semibold text-ink tabular-nums">{item.amount.display}</span>
                  <span className="text-xs text-muted tabular-nums">{item.share?.display}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {active && CONTENTS[active.key] && (
        <button
          type="button"
          onClick={() => askInThread(CONTENTS[active.key][lang])}
          className="inline-flex min-h-11 items-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-sm font-semibold text-brand hover:bg-mint-tint"
        >
          {CONTENTS[active.key][lang]}
        </button>
      )}
    </div>
  )
}
