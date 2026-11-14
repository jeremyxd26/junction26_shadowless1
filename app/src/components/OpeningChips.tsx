import { useEffect, useRef, type KeyboardEvent } from 'react'
import { chatStrings } from '../lib/chatStrings.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { askInThread } from '../lib/url.ts'
import { clientTurnRequest, clientTurns, openingChips, prefetchClientTurns } from './clientTurns.tsx'

/** A chip: 36 px, its ::after keeps the 44 px target inside the row's vertical padding. */
const CHIP =
  "relative min-h-9 whitespace-nowrap rounded-md border border-line bg-surface px-3 py-1.5 text-[0.9375rem] leading-5 text-ink hover:bg-sunken after:absolute after:inset-x-0 after:-inset-y-1 after:content-['']"

interface Item {
  id: string
  text: string
  act: () => void
}

/**
 * The opening's chips in one horizontally scrollable row (Renat's decision): the first two questions,
 * the client-turn chips (#319, `openingChips` order, without the API), then more questions the core
 * answers well. The row snaps, a fade at the right edge says there is more, and Left / Right arrows
 * move between chips (Tab reaches each one too, and the row scrolls it into view).
 */
export function OpeningChips() {
  // The client turns' code loads at idle once the opening shows, ahead of the first tap (#728).
  useEffect(() => prefetchClientTurns(), [])
  const { lang, t } = useSettings()
  const opening = useOpening()
  const list = useRef<HTMLUListElement>(null)
  if (!opening) return null
  const s = chatStrings(lang)
  const ask = (question: string): Item => ({ id: `q:${question}`, text: question, act: () => askInThread(question) })
  const client = openingChips
    .filter((key) => clientTurns[key]?.visible())
    .map((key): Item => {
      const request = clientTurnRequest(key, lang)
      return { id: `c:${key}`, text: request.question, act: () => opening.pushClientTurn(request) }
    })
  const items = [...s.openingFirst.map(ask), ...client, ...s.openingMore.map(ask)]

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    const buttons = [...(list.current?.querySelectorAll('button') ?? [])]
    const at = buttons.findIndex((button) => button === document.activeElement)
    if (at < 0) return
    event.preventDefault()
    buttons[Math.min(buttons.length - 1, Math.max(0, at + (event.key === 'ArrowRight' ? 1 : -1)))]?.focus()
  }

  return (
    <div className="relative -mx-4">
      <ul
        ref={list}
        data-opening-part="client-chips"
        aria-label={t.questionsLabel}
        onKeyDown={onKeyDown}
        className="flex snap-x snap-mandatory scroll-px-4 gap-2 overflow-x-auto px-4 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item) => (
          <li key={item.id} className="shrink-0 snap-start">
            <button type="button" onClick={item.act} className={CHIP}>
              {item.text}
            </button>
          </li>
        ))}
      </ul>
      {/* There is more to the right. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 w-10"
        style={{ background: 'linear-gradient(to left, var(--color-page), transparent)' }}
      />
    </div>
  )
}
