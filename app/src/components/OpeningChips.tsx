import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { chatStrings } from '../lib/chatStrings.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { askInThread } from '../lib/url.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { clientTurnRequest, clientTurns, openingChips, prefetchClientTurns } from './clientTurns.tsx'

const ICONS: Record<string, ReactNode> = {
  money: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3v9h9" />
    </>
  ),
  bills: (
    <>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v4h4M10 12h5M10 16h5" />
    </>
  ),
  whatif: <path d="M4 17l5-5 4 4 7-7M15 9h5v5" />,
}

/**
 * The opening's ways in (Renat's review): three full-width entry cards (icon, title, one line), each
 * sending its existing question, then "More questions ›", which opens a sheet with every question and
 * the client chips (#319: "Show Sentti a bill"). Nothing is cut off at 375 px.
 */
export function OpeningChips() {
  // The client turns' code loads at idle once the opening shows, ahead of the first tap (#728).
  useEffect(() => prefetchClientTurns(), [])
  const { lang, t } = useSettings()
  const opening = useOpening()
  const [more, setMore] = useState(false)
  if (!opening) return null
  const s = chatStrings(lang)
  const cards = s.entryCards
  const client = openingChips
    .filter((key) => clientTurns[key]?.visible())
    .map((key) => {
      const request = clientTurnRequest(key, lang)
      return { id: `c:${key}`, text: request.question, act: () => opening.pushClientTurn(request) }
    })
  const ask = (question: string) => ({ id: `q:${question}`, text: question, act: () => askInThread(question) })
  const items = [...s.openingFirst.map(ask), ...client, ...s.openingMore.map(ask)]

  const sheet = (
    <BottomSheet title={t.questionsLabel} onClose={() => setMore(false)}>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => {
                setMore(false)
                item.act()
              }}
              className="flex min-h-11 w-full items-center rounded-md border border-line bg-surface px-4 py-2 text-left text-base text-ink hover:bg-sunken"
            >
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </BottomSheet>
  )

  return (
    <div data-opening-part="client-chips" className="flex flex-col gap-2">
      <ul aria-label={t.questionsLabel} className="flex flex-col gap-2">
        {cards.map((card) => (
          <li key={card.key}>
            <button
              type="button"
              onClick={() => askInThread(card.question)}
              className="flex min-h-14 w-full items-center gap-3 rounded-lg border border-line bg-surface p-3 text-left hover:bg-sunken"
            >
              <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-mint-tint text-brand">
                <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  {ICONS[card.key]}
                </svg>
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-base font-semibold text-ink">{card.title}</span>
                <span className="text-sm text-ink-2">{card.line}</span>
              </span>
              <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => setMore(true)}
        aria-haspopup="dialog"
        className="inline-flex min-h-11 items-center gap-1 self-start rounded-pill px-3 text-base font-semibold text-brand hover:bg-sunken"
      >
        {s.moreQuestions}
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.25">
          <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {/* In a portal: an animated ancestor would pin a fixed sheet to it. */}
      {more && (typeof document !== 'undefined' ? createPortal(sheet, document.body) : sheet)}
    </div>
  )
}
