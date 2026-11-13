import type { ReactNode } from 'react'
import type { Action, BreakdownCard, Insight, MetricCard, Num, ReviewCard, SafeToSpendStatus } from '../api/types.ts'
import { navigate, openEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { EstimateBadge } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'

function CardShell({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface p-4 ${className}`}>{children}</section>
}

function ActionButton({ action, primary = false }: { action: Action; primary?: boolean }) {
  const base = 'inline-flex min-h-11 items-center justify-center rounded-pill px-4 text-base font-semibold'
  const look = primary ? 'bg-mint text-ink hover:bg-mint-hover' : 'border border-mint-line bg-surface text-brand hover:bg-mint-tint'
  if (action.type === 'open_evidence') {
    return (
      <button type="button" className={`${base} ${look}`} onClick={() => openEvidence(action.evidence_ref)}>
        {action.label}
      </button>
    )
  }
  if (action.type === 'ask') {
    return (
      <button type="button" className={`${base} ${look}`} onClick={() => navigate('/chat', { q: action.prompt })}>
        {action.label}
      </button>
    )
  }
  return null
}

const statusTone: Record<SafeToSpendStatus, { chip: 'mint' | 'warning' | 'neutral'; dot: string }> = {
  ok: { chip: 'mint', dot: 'bg-brand' },
  below_usual: { chip: 'warning', dot: 'bg-warning' },
  nothing_free: { chip: 'neutral', dot: 'bg-muted' },
}

/** The weekly safe-to-spend card: one primary number, one line about the reserve. */
export function HeroCard({ card }: { card: MetricCard }) {
  const { t } = useSettings()
  const status = card.status ?? 'ok'
  const tone = statusTone[status] ?? statusTone.ok
  const reserve = card.components.find((component) => component.key === 'irregular_reserve')
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink">{card.title}</h2>
          {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
        </div>
        {card.estimate && <EstimateBadge estimate={card.estimate} />}
      </div>

      <div className="mt-3">
        <NumberChip number={card.primary} size="hero" tone={tone.chip} />
      </div>
      <p className="mt-2 flex items-center gap-2 text-sm font-semibold text-ink">
        <span aria-hidden="true" className={`size-2.5 rounded-pill ${tone.dot}`} />
        {t.status[status] ?? ''}
      </p>

      {reserve && (
        <p className="mt-3 text-base leading-8 text-ink-2">
          {reserve.label} <NumberChip number={reserve.amount} size="inline" /> {t.keptAside}.
        </p>
      )}

      {card.actions.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {card.actions.map((action, index) => (
            <ActionButton key={`${action.type}-${index}`} action={action} />
          ))}
        </div>
      )}
    </CardShell>
  )
}

const BASKETS: Record<string, { icon: string; color: string; tint: string; bar: string }> = {
  regular_essentials: {
    icon: '🏠',
    color: 'text-basket-essentials',
    tint: 'bg-basket-essentials-tint',
    bar: 'bg-basket-essentials',
  },
  unexpected_necessities: {
    icon: '🔧',
    color: 'text-basket-unexpected',
    tint: 'bg-basket-unexpected-tint',
    bar: 'bg-basket-unexpected',
  },
  everyday_spending: {
    icon: '☕️',
    color: 'text-basket-everyday',
    tint: 'bg-basket-everyday-tint',
    bar: 'bg-basket-everyday',
  },
  unclassified: { icon: '?', color: 'text-waiting', tint: 'bg-waiting-tint', bar: 'bg-line-strong' },
}

/** The three baskets, always icon + label + colour; a pending purchase shows as a fourth, neutral row. */
export function BasketsCard({ card }: { card: BreakdownCard }) {
  const items = card.items.filter((item) => item.key in BASKETS)
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink">{card.title}</h2>
          {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
        </div>
        {card.estimate && <EstimateBadge estimate={card.estimate} />}
      </div>

      {/* Visual only: widths follow the API's share numbers; the numbers themselves are the chips below. */}
      <div aria-hidden="true" className="mt-4 flex h-3 w-full gap-0.5 overflow-hidden rounded-pill bg-sunken">
        {items.map((item) => (
          <div key={item.key} className={BASKETS[item.key].bar} style={{ width: `${item.share?.value ?? 0}%` }} />
        ))}
      </div>

      <ul className="mt-3 flex flex-col">
        {items.map((item) => {
          const look = BASKETS[item.key]
          return (
            <li key={item.key} className="flex gap-3 border-b border-line py-2.5 last:border-b-0">
              <span
                aria-hidden="true"
                className={`inline-flex size-10 shrink-0 items-center justify-center rounded-pill text-lg font-bold ${look.tint} ${look.color}`}
              >
                {look.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex min-h-10 items-center justify-between gap-2">
                  <span className={`font-semibold ${look.color}`}>{item.label}</span>
                  {item.share && <NumberChip number={item.share} size="inline" tone="neutral" />}
                </div>
                <NumberChip number={item.amount} />
              </div>
            </li>
          )
        })}
      </ul>
      <div className="mt-2 flex items-center justify-between gap-2 text-sm text-muted">
        <span>{card.total.label}</span>
        <NumberChip number={card.total} />
      </div>
    </CardShell>
  )
}

/**
 * Placeholder for the review question (`reviews[0]`, state `unclassified`).
 * Answering it (POST /api/baskets/label) is issue #35.
 */
export function ReviewPlaceholder({ card }: { card: ReviewCard }) {
  const { lang, t } = useSettings()
  return (
    <CardShell className="border-mint-line">
      <span className="inline-flex items-center gap-1 rounded-pill bg-waiting-tint px-2.5 py-1 text-xs font-semibold text-waiting">
        <span aria-hidden="true">?</span>
        {card.current_basket.label}
      </span>
      <h2 className="mt-2 text-lg font-semibold text-ink">{card.title}</h2>
      {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <NumberChip number={card.amount} />
        {card.merchant && <span className="text-sm text-muted">{card.merchant.label}</span>}
      </div>
      <p className="mt-3 text-base text-ink-2">{card.question[lang]}</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {card.options.map((option) => (
          <button
            key={option.basket}
            type="button"
            aria-disabled="true"
            className="min-h-11 cursor-not-allowed rounded-pill border border-line bg-sunken px-3 text-base font-semibold text-muted"
          >
            {option.label[lang]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-sm text-muted">{t.reviewSoon}</p>
    </CardShell>
  )
}

const TOKEN = /\{\{(n[0-9]+)\}\}/g

/** Text with number tokens (contract 2.4): each token becomes a chip with the number's `display`. */
export function TokenText({ text, numbers }: { text: string; numbers: Record<string, Num> }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last) parts.push(text.slice(last, index))
    const number = numbers[match[1]]
    parts.push(number ? <NumberChip key={`${match[1]}-${index}`} number={number} size="inline" /> : match[0])
    last = index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

export function InsightCard({ insight }: { insight: Insight }) {
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-ink">{insight.title}</h3>
        {insight.estimate && <EstimateBadge estimate={insight.estimate} />}
      </div>
      <p className="mt-1 text-base leading-8 text-ink-2">
        <TokenText text={insight.text} numbers={insight.numbers} />
      </p>
      {insight.action && (
        <div className="mt-2">
          <ActionButton action={insight.action} />
        </div>
      )}
    </CardShell>
  )
}
