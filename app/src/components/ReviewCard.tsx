import { forwardRef, useId, type ReactNode } from 'react'
import type { BasketKey, ReviewCard as ReviewCardData } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { formatDate } from '../lib/i18n.ts'
import { openEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { Check } from './cards.tsx'
import { NumberChip } from './NumberChip.tsx'

/** The deep-green "Sentti asks" surface: never the hero green, so a question never looks like an answer. */
const SURFACE = 'rounded-xl bg-deep p-4 text-on-deep outline-none [&_:focus-visible]:outline-mint'

const TOKEN = /\{\{(\w+)\}\}/g

/** Fills `{{name}}` in an app template with text or chips. */
function fill(template: string, parts: Record<string, ReactNode>): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const match of template.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last) out.push(template.slice(last, index))
    out.push(<span key={`${match[1]}-${index}`}>{parts[match[1]] ?? match[0]}</span>)
    last = index + match[0].length
  }
  if (last < template.length) out.push(template.slice(last))
  return out
}

export interface ReviewError {
  message: string
  retryable: boolean
}

interface AskingProps {
  card: ReviewCardData
  /** The basket whose answer is being sent; both buttons wait meanwhile. */
  busy: BasketKey | null
  error: ReviewError | null
  onAnswer: (basket: BasketKey) => void
  onNotSure: () => void
  onRetry: () => void
  leaving: boolean
}

/** The question about one spending spike (contract `review` card, texts from #68). */
export const ReviewAsking = forwardRef<HTMLElement, AskingProps>(function ReviewAsking(
  { card, busy, error, onAnswer, onNotSure, onRetry, leaving },
  ref,
) {
  const { lang, t } = useSettings()
  const titleId = useId()
  const date = formatDate(card.date, lang)
  const purchaseRef = card.evidence_ref ?? card.amount.evidence_ref
  const seePurchase = card.actions.find((action) => action.type === 'open_evidence')?.label ?? t.reviewSeePurchase

  const question = fill(t.reviewQuestion, {
    n1: <NumberChip number={card.amount} size="lead" />,
    category: card.category,
    date: purchaseRef ? (
      <button
        type="button"
        onClick={() => openEvidence(purchaseRef)}
        aria-label={`${date}. ${seePurchase}`}
        className="relative inline-flex min-h-9 items-center rounded-pill border border-on-deep-muted/60 px-3 align-baseline hover:border-on-deep after:absolute after:-inset-y-1 after:inset-x-0 after:content-['']"
      >
        {date}
      </button>
    ) : (
      date
    ),
  })

  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={titleId}
      aria-busy={busy !== null}
      className={`${SURFACE} ${leaving ? 'card-leave' : 'card-enter'}`}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-pill bg-mint text-lg font-bold text-ink"
        >
          ?
        </span>
        <h2 id={titleId} className="flex-1 text-base font-semibold text-on-deep">
          {t.reviewAsks}
        </h2>
        {/* Client only: closes the card; the purchase keeps waiting for an answer. */}
        <button
          type="button"
          onClick={onNotSure}
          disabled={busy !== null}
          className="-mr-1 min-h-11 px-1 text-sm font-semibold text-on-deep-muted underline underline-offset-4 hover:text-on-deep"
        >
          {t.reviewNotSure}
        </button>
      </div>

      <p className="mt-3 text-xl font-bold leading-9 text-on-deep">{question}</p>
      {card.merchant && <p className="mt-1 text-sm text-on-deep-muted">{card.merchant.label}</p>}

      <div className="mt-4 grid grid-cols-2 gap-2">
        {card.options.map((option) => {
          const look = BASKETS[option.basket]
          const label = t.reviewAnswers[option.basket] ?? option.label[lang]
          const chosen = busy === option.basket
          return (
            <button
              key={option.basket}
              type="button"
              onClick={() => onAnswer(option.basket)}
              disabled={busy !== null}
              className={`flex min-h-[84px] flex-col items-center justify-center gap-1.5 rounded-lg border-t-4 bg-surface px-2 pb-3 pt-2 text-base font-bold text-ink transition-transform duration-150 active:scale-[.97] disabled:cursor-wait ${look.line} ${
                chosen ? 'outline-3 outline-offset-2 outline-mint' : ''
              }`}
            >
              <span aria-hidden="true" className={`inline-flex size-9 items-center justify-center rounded-md text-lg ${look.tint}`}>
                {look.icon}
              </span>
              {label}
            </button>
          )
        })}
      </div>

      {error && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-danger-tint px-3 py-2 text-sm text-ink">
          <span className="flex-1">{error.message}</span>
          {error.retryable && (
            <button type="button" onClick={onRetry} className="min-h-11 font-semibold text-danger underline underline-offset-4">
              {t.retry}
            </button>
          )}
        </div>
      )}
    </section>
  )
})

interface AnsweredProps {
  card: ReviewCardData
  basket: BasketKey
}

/** After the tap: one line with a check, the chosen answer and what it does (`options[].effect`). */
export const ReviewAnswered = forwardRef<HTMLElement, AnsweredProps>(function ReviewAnswered({ card, basket }, ref) {
  const { lang, t } = useSettings()
  const titleId = useId()
  const option = card.options.find((candidate) => candidate.basket === basket)
  const look = BASKETS[basket]
  return (
    <section ref={ref} tabIndex={-1} aria-labelledby={titleId} className={`${SURFACE} card-enter`}>
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-pill bg-mint text-ink">
          <Check className="size-5" />
        </span>
        <span aria-hidden="true" className="text-lg">
          {look?.icon}
        </span>
        <h2 id={titleId} className="text-lg font-bold text-on-deep">
          {t.reviewAnswers[basket] ?? option?.label[lang]}
        </h2>
      </div>
      {option && <p className="mt-2 text-base text-on-deep-muted">{option.effect[lang]}</p>}
    </section>
  )
})
