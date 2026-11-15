import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { chatStrings } from '../lib/chatStrings.ts'
import { usePrefersReducedMotion } from '../lib/motion.ts'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { askInThread } from '../lib/url.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { clientTurnRequest, clientTurns, openingChips, prefetchClientTurns } from './clientTurns.tsx'

/** Small line icons for the chips, in the order of the questions: `openingFirst` then `openingMore`. */
const QUESTION_ICONS: ReactNode[] = [
  // Where did my money go?
  <>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 4v8h8" />
  </>,
  // How could I save more?
  <>
    <path d="M5 12a7 7 0 0 1 12.5-4.3M19 12a7 7 0 0 1-12.5 4.3" />
    <path d="M17.5 4v3.7h-3.7M6.5 20v-3.7h3.7" />
  </>,
  // What kind of spender am I?
  <>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20c1.2-3.5 3.8-5 7-5s5.8 1.5 7 5" />
  </>,
  // How do I compare with people like me?
  <>
    <circle cx="9" cy="9" r="3" />
    <circle cx="16.5" cy="10" r="2.5" />
    <path d="M3.5 19c.9-2.8 3-4 5.5-4s4.6 1.2 5.5 4M15 15.2c2.6-.3 4.6.9 5.5 3.8" />
  </>,
  // What if I spent 20% less on restaurants?
  <path d="M4 17l5-5 4 4 7-7M15 9h5v5" />,
  // What are my regular monthly bills?
  <>
    <path d="M7 3h7l4 4v14H7z" />
    <path d="M14 3v4h4M10 12h5M10 16h5" />
  </>,
  // Will my money last until payday?
  <>
    <rect x="4" y="5" width="16" height="15" rx="2" />
    <path d="M4 10h16M9 3v4M15 3v4" />
  </>,
  // Where do my small purchases go?
  <>
    <path d="M6 8h12l-1 12H7z" />
    <path d="M9 8a3 3 0 0 1 6 0" />
  </>,
]
/** The client chips' icon (#319: "Show Sentti a bill"): a paperclip, like the composer's. */
const CLIENT_ICON = <path d="M16.5 7.5l-7 7a2 2 0 0 0 2.8 2.8l7.2-7.2a4 4 0 0 0-5.7-5.7l-7.4 7.4a6 6 0 0 0 8.5 8.5l6.6-6.6" />

/** Chips in the first row; the rest go in the second. */
const FIRST_ROW = 5

interface Item {
  id: string
  text: string
  icon: ReactNode
  act: () => void
}

/** A row: edge to edge (out of the page's 16px gutters), faded at both edges so no chip looks cut off. */
const ROW = '-mx-4 flex gap-2 [mask-image:linear-gradient(to_right,transparent,#000_16px,#000_calc(100%-16px),transparent)]'

function Chip({ item, hidden = false }: { item: Item; hidden?: boolean }) {
  return (
    <button
      type="button"
      onClick={item.act}
      tabIndex={hidden ? -1 : undefined}
      className="inline-flex min-h-11 items-center gap-1.5 rounded-pill border border-line bg-surface px-3 text-sm whitespace-nowrap text-ink hover:bg-sunken"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0 text-brand" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {item.icon}
      </svg>
      {item.text}
    </button>
  )
}

/** How long the drift stays stopped after a finger leaves the row. */
const RESUME_MS = 2000

/**
 * A row that drifts slowly sideways (Renat's light redesign): the chips twice on one track that moves by half its
 * width (`.chip-drift` in index.css), so the loop never shows a gap. The second copy is hidden from screen readers
 * and the tab order but still answers a tap. The drift stops while the pointer is on the row, a chip has focus, or
 * for a moment after a touch, so a moving chip is never hard to tap.
 */
function DriftRow({ row, label, reverse, seconds }: { row: Item[]; label?: string; reverse: boolean; seconds: number }) {
  const [paused, setPaused] = useState(false)
  const resume = useRef(0)
  useEffect(() => () => window.clearTimeout(resume.current), [])
  const hold = () => {
    window.clearTimeout(resume.current)
    setPaused(true)
  }
  const release = () => {
    window.clearTimeout(resume.current)
    resume.current = window.setTimeout(() => setPaused(false), RESUME_MS)
  }
  return (
    <div data-chip-row="" onPointerDown={hold} onPointerUp={release} onPointerCancel={release} className={`${ROW} overflow-hidden pl-4`}>
      <div
        data-paused={paused ? '' : undefined}
        className={`chip-drift flex w-max ${reverse ? 'chip-drift-reverse' : ''}`}
        style={{ ['--drift-duration' as string]: `${seconds}s` }}
      >
        {[0, 1].map((copy) => (
          <ul key={copy} aria-label={copy === 0 ? label : undefined} aria-hidden={copy === 1 ? true : undefined} className="flex shrink-0 gap-2 pr-2">
            {row.map((item) => (
              <li key={item.id} className="shrink-0">
                <Chip item={item} hidden={copy === 1} />
              </li>
            ))}
          </ul>
        ))}
      </div>
    </div>
  )
}

/**
 * The opening's ways in (Renat's light redesign): small pill chips with line icons in two rows that scroll
 * sideways, with soft fades at both edges so no chip looks cut off, then a centred "More questions" pill that
 * opens the sheet with every question and the client chips (#319: "Show Sentti a bill"). Each chip sends its
 * question as it is; 44px targets at any text size.
 */
export function OpeningChips() {
  // The client turns' code loads at idle once the opening shows, ahead of the first tap (#728).
  useEffect(() => prefetchClientTurns(), [])
  const { lang, t } = useSettings()
  const opening = useOpening()
  const [more, setMore] = useState(false)
  const reduced = usePrefersReducedMotion()
  if (!opening) return null
  const s = chatStrings(lang)
  const client: Item[] = openingChips
    .filter((key) => clientTurns[key]?.visible())
    .map((key) => {
      const request = clientTurnRequest(key, lang)
      return { id: `c:${key}`, text: request.question, icon: CLIENT_ICON, act: () => opening.pushClientTurn(request) }
    })
  const questions = [...s.openingFirst, ...s.openingMore]
  const ask = (question: string): Item => ({
    id: `q:${question}`,
    text: question,
    icon: QUESTION_ICONS[questions.indexOf(question)] ?? QUESTION_ICONS[0],
    act: () => askInThread(question),
  })
  const items = [...s.openingFirst.map(ask), ...client, ...s.openingMore.map(ask)]
  const rows = [items.slice(0, FIRST_ROW), items.slice(FIRST_ROW)].filter((row) => row.length > 0)

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
    <div data-opening-part="client-chips" className="flex flex-col gap-2 pt-1">
      {rows.map((row, index) =>
        reduced ? (
          // Reduced motion: still rows that scroll sideways by hand, without a bar.
          <ul key={index} aria-label={index === 0 ? t.questionsLabel : undefined} className={`${ROW} overflow-x-auto px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden`}>
            {row.map((item) => (
              <li key={item.id} className="shrink-0">
                <Chip item={item} />
              </li>
            ))}
          </ul>
        ) : (
          <DriftRow key={index} row={row} label={index === 0 ? t.questionsLabel : undefined} reverse={index % 2 === 1} seconds={index % 2 === 1 ? 38 : 45} />
        ),
      )}
      <button
        type="button"
        onClick={() => setMore(true)}
        aria-haspopup="dialog"
        className="mt-1 inline-flex min-h-11 items-center gap-1 self-center rounded-pill border border-line-strong bg-surface px-4 text-sm font-semibold text-ink hover:bg-sunken"
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
