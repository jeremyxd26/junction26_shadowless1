// The cards of a chat answer (`card` events, contract sections 3 and 7.2), one renderer per
// `type` in the shared answer-card frame (DESIGN.md "Answer card"). Card `actions` are not
// drawn here: the chat shows them as action chips under the explanation.
import { Component, type ReactNode } from 'react'
import type { BreakdownCard, Card, Comparison, MetricCard, Num, SafeToSaveCard as SafeToSaveData } from '../api/types.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { BillsCards } from './BillsCard.tsx'
import { BasketsCard, CARD_TITLE, CardShell } from './cards.tsx'
import { EstimateBadge } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'
import { PeerCard, type PeerData } from './PeerCard.tsx'
import { ProfileCard, type ProfileData } from './ProfileCard.tsx'
import { SafeToSaveCard } from './SafeToSaveCard.tsx'

/** Title, subtitle and the fact or estimate marker, top right. */
function CardHeader({ card }: { card: Card }) {
  const { lang } = useSettings()
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className={CARD_TITLE}>{card.title}</h3>
        {card.subtitle && <p className="mt-0.5 text-sm text-muted">{card.subtitle}</p>}
      </div>
      {card.estimate ? (
        <EstimateBadge estimate={card.estimate} />
      ) : (
        <span className="max-w-[45%] shrink-0 pt-0.5 text-right text-xs [overflow-wrap:anywhere] text-muted">{chatStrings(lang).fact}</span>
      )}
    </div>
  )
}

/** --color-up and --color-down have the values of brand and warning, which Tailwind maps. */
const TONE: Record<Comparison['tone'], string> = {
  better: 'text-brand',
  worse: 'text-warning',
  neutral: 'text-muted',
}

/** "▲ €91.70 more": an arrow and a word, never colour alone (DESIGN.md section 4). */
function Change({ change, pct, tone = 'neutral' }: { change: Num; pct?: Num | null; tone?: Comparison['tone'] }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  const arrow = change.value > 0 ? '▲' : change.value < 0 ? '▼' : '•'
  const word = change.value > 0 ? s.more : change.value < 0 ? s.less : s.same
  return (
    <span className={`inline-flex flex-wrap items-center gap-x-1.5 gap-y-1 ${TONE[tone] ?? TONE.neutral}`}>
      <span aria-hidden="true">{arrow}</span>
      <NumberChip number={change} size="inline" tone="neutral" />
      {pct && <NumberChip number={pct} size="inline" tone="neutral" />}
      <span className="font-semibold">{word}</span>
    </span>
  )
}

function ComparisonLine({ comparison }: { comparison: Comparison }) {
  return (
    <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm leading-8">
      <Change change={comparison.change} pct={comparison.change_pct} tone={comparison.tone} />
      <span className="text-muted">{comparison.label}</span>
    </p>
  )
}

function MetricAnswer({ card }: { card: MetricCard }) {
  return (
    <CardShell>
      <CardHeader card={card} />
      <div className="mt-3">
        <NumberChip number={card.primary} size="lg" />
      </div>
      {card.secondary?.length > 0 && (
        <ul className="mt-3 flex flex-col">
          {card.secondary.map((number, index) => (
            <li key={number.id ?? index} className="flex min-h-11 items-center justify-between gap-3 border-t border-line">
              <span className="text-sm text-muted">{number.label}</span>
              <NumberChip number={number} size="inline" />
            </li>
          ))}
        </ul>
      )}
      {card.comparison && <ComparisonLine comparison={card.comparison} />}
    </CardShell>
  )
}

/** A category breakdown: total, comparison and one row per item with its change. */
function BreakdownAnswer({ card }: { card: BreakdownCard }) {
  const { lang } = useSettings()
  const s = chatStrings(lang)
  return (
    <CardShell>
      <CardHeader card={card} />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted">{card.total.label}</span>
        <NumberChip number={card.total} />
      </div>
      {card.comparison && <ComparisonLine comparison={card.comparison} />}
      <ul className="mt-2 flex flex-col">
        {card.items.map((item) => (
          <li key={item.key} className="border-t border-line py-2.5">
            <div className="flex min-h-11 items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-bold text-brand">{item.label}</span>
                {item.flags.map((flag) =>
                  s.flags[flag] ? (
                    <span key={flag} className="rounded-sm bg-sunken px-1.5 py-0.5 text-xs font-semibold text-muted">
                      {s.flags[flag]}
                    </span>
                  ) : null,
                )}
              </div>
              <NumberChip number={item.amount} />
            </div>
            {(item.change || item.share) && (
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm leading-8">
                {item.change && <Change change={item.change} />}
                {item.share && <NumberChip number={item.share} size="inline" tone="neutral" />}
              </p>
            )}
          </li>
        ))}
      </ul>
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

function isBasketsBreakdown(card: BreakdownCard): boolean {
  return card.items.some((item) => item.key === 'regular_essentials')
}

function CardBody({ card }: { card: Card }) {
  switch (card.type) {
    case 'metric':
      return <MetricAnswer card={card as MetricCard} />
    case 'breakdown': {
      const breakdown = card as BreakdownCard
      return isBasketsBreakdown(breakdown) ? <BasketsCard card={breakdown} /> : <BreakdownAnswer card={breakdown} />
    }
    case 'safe_to_save':
      // Card actions show as chips under the answer (AnswerView), so the card itself draws none.
      return <SafeToSaveCard card={{ ...(card as SafeToSaveData), actions: [] }} />
    case 'profile':
      return <ProfileCard card={card as ProfileData} header={<CardHeader card={card} />} />
    case 'peer':
      return <PeerCard card={card as PeerData} header={<CardHeader card={card} />} />
    case 'bills':
      return <BillsCards cards={[{ ...card, actions: [] }]} />
    // Any other type gets the generic card, `review` included: it is answered in "Sentti asks" (#35).
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

export function AnswerCard({ card }: { card: Card }) {
  return (
    <CardBoundary card={card}>
      <CardBody card={card} />
    </CardBoundary>
  )
}
