// The cards of a chat answer (`card` events, contract sections 3 and 7.2). The question is in the
// bubble and the sentence above the card, so a card reads as part of one answer (#684): no title
// (it restates the question), the period once as a caption, one main number, at most three
// "label — value" rows, and numbers as text, not pills. `lib/answerFigures.ts` picks the fields
// by card type; the baskets breakdown and the bills too (#696). The review keeps its own card. Card `actions`
// are not drawn here: the answer shows at most one next step under the text.
import { Component, type ReactNode } from 'react'
import type { Card, Comparison, Num, ReviewCard } from '../api/types.ts'
import { answerFigures, asLaterCard, type AnswerFigures, type FigureRow } from '../lib/answerFigures.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { useEstimateToggle } from '../lib/useEstimateToggle.ts'
import { CARD_TITLE, CardShell } from './cards.tsx'
import { EstimateBadge, EstimateNote } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'
import { ReviewPointer } from './ReviewPointer.tsx'

/** Title, subtitle and the estimate marker, top right; a fact card has no marker (#685). */
function CardHeader({ card }: { card: Card }) {
  return (
    // With large text the marker moves under the title instead of covering it (#541).
    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
      <div className="min-w-[min(6rem,100%)] flex-1 basis-0">
        <h3 className={CARD_TITLE}>{card.title}</h3>
        {card.subtitle && <p className="mt-0.5 text-sm text-muted">{card.subtitle}</p>}
      </div>
      {card.estimate && (
        <span className="ml-auto shrink-0">
          <EstimateBadge estimate={card.estimate} />
        </span>
      )}
    </div>
  )
}

/** --color-up and --color-down have the values of brand and warning, which Tailwind maps. */
const TONE: Record<Comparison['tone'], string> = {
  better: 'text-brand',
  worse: 'text-warning',
  neutral: 'text-ink',
}

/** "▲ €91.70 more": an arrow and a word, never colour alone (DESIGN.md section 4). */
function Change({ change, tone = 'neutral' }: { change: Num; tone?: Comparison['tone'] }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const arrow = change.value > 0 ? '▲' : change.value < 0 ? '▼' : '•'
  const word = change.value > 0 ? s.more : change.value < 0 ? s.less : s.same
  return (
    <span className={`inline-flex flex-wrap items-center justify-end gap-x-1.5 gap-y-1 ${TONE[tone] ?? TONE.neutral}`}>
      <span aria-hidden="true">{arrow}</span>
      <NumberChip number={change} size="inline" tone="plain" wrap />
      <span className="font-semibold">{word}</span>
    </span>
  )
}

function Row({ row }: { row: FigureRow }) {
  return (
    // With large text the value moves under the label instead of covering it (#541).
    <li data-figure-row="" className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line py-1.5">
      <span className="min-w-[min(6rem,100%)] flex-1 basis-0 text-sm text-muted">{row.label}</span>
      <span className="ml-auto max-w-full shrink-0 text-right text-base text-ink">
        {row.tone ? <Change change={row.number} tone={row.tone} /> : <NumberChip number={row.number} size="inline" tone="plain" wrap />}
      </span>
    </li>
  )
}

/** One card of an answer: caption and estimate marker, the result's name, the main number, the rows. */
function AnswerFrame({ card, figures }: { card: Card; figures: AnswerFigures }) {
  const estimate = useEstimateToggle()
  const { caption, title, tags, main, rows, note, caveats } = figures
  return (
    <CardShell>
      {(caption || card.estimate) && (
        <div className="flex flex-wrap items-center justify-between gap-x-3">
          {caption && <p data-answer-caption="" className="min-w-0 flex-1 text-xs text-muted">{caption}</p>}
          {card.estimate && (
            <span className="-my-2 ml-auto shrink-0">
              <EstimateBadge estimate={card.estimate} control={estimate.control} />
            </span>
          )}
        </div>
      )}
      {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} />}
      {title && <p className="mt-2 text-lg leading-7 text-ink">{title}</p>}
      {tags.length > 0 && <p className="mt-0.5 text-sm text-muted">{tags.join(' · ')}</p>}
      {main && (
        <div data-answer-main="" className="mt-2 flex flex-col items-start">
          <span className="text-base text-ink-2">{main.label}</span>
          <span className="max-w-full text-ink">
            <NumberChip number={main} size="lg" tone="plain" />
          </span>
        </div>
      )}
      {rows.length > 0 && (
        <ul className="mt-2 flex flex-col">
          {rows.map((row) => (
            <Row key={row.key} row={row} />
          ))}
        </ul>
      )}
      {note && <p className="mt-1 text-sm text-muted">{note}</p>}
      {/* A what-if's caveats, as the what-if sheet shows them (#696). */}
      {caveats.length > 0 && (
        <div data-answer-caveats="" className="mt-2 rounded-md bg-warning-tint p-3 text-base text-ink">
          {caveats.map((caveat) => (
            <p key={caveat}>{caveat}</p>
          ))}
        </div>
      )}
    </CardShell>
  )
}

/** A card type without its own renderer yet (DESIGN.md section 8): the frame and its marker. */
function GenericAnswer({ card }: { card: Card }) {
  return (
    <CardShell>
      <CardHeader card={card} />
    </CardShell>
  )
}

/** Where the card stands in its answer: a later card has no large number of its own. */
interface Place {
  later?: boolean
  /** The caption of the card before it, so the same period is not shown twice. */
  previousCaption?: string | null
}

function CardBody({ card, later = false, previousCaption = null }: { card: Card } & Place) {
  const own = answerFigures(card)
  const figures = own && later ? asLaterCard(own, previousCaption) : own
  if (figures) return <AnswerFrame card={card} figures={figures} />
  switch (card.type) {
    // A review is asked once, in the opening; the answer points there (#318).
    case 'review':
      return <ReviewPointer card={card as ReviewCard} />
    // Any other type gets the generic card.
    default:
      return <GenericAnswer card={card} />
  }
}

/**
 * One malformed card (for example a breakdown without `items`) must not take the whole chat
 * down: it falls back to the shared frame with its title, and the rest of the answer stays.
 */
class CardBoundary extends Component<{ card: Card; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('Sentti card failed', this.props.card.type, error)
  }

  componentDidUpdate(previous: { card: Card }) {
    // A new version of the card (same card_id) gets a fresh try.
    if (this.state.failed && previous.card !== this.props.card) this.setState({ failed: false })
  }

  render() {
    return this.state.failed ? <GenericAnswer card={this.props.card} /> : this.props.children
  }
}

export function AnswerCard({ card, later, previousCaption }: { card: Card } & Place) {
  return (
    <CardBoundary card={card}>
      <CardBody card={card} later={later} previousCaption={previousCaption} />
    </CardBoundary>
  )
}
