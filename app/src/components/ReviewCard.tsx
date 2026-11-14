import { forwardRef, useId, type ReactNode } from 'react'
import type { BasketKey, ReviewCard as ReviewCardData } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { formatDate } from '../lib/i18n.ts'
import { openEvidence } from '../lib/url.ts'
import { useCountdown } from '../lib/useCountdown.ts'
import { useSettings } from '../lib/settings.ts'
import { Check } from './cards.tsx'
import { NumberChip } from './NumberChip.tsx'
import { RetryButton } from './RetryButton.tsx'

/** The deep-green "Sentti asks" surface: never the hero green, so a question never looks like an answer. */
const SURFACE = 'rounded-xl bg-deep p-4 text-on-deep outline-none [&_:focus-visible]:outline-mint'

/** Tokens the question may carry: `{{n1}}` is the card's amount, `{{date}}` its date. */
const TOKEN = /\{\{(n1|date)\}\}/g

/** The question as the API sends it; its tokens, if any, become chips. */
function fill(text: string, parts: Record<string, ReactNode>): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last) out.push(text.slice(last, index))
    out.push(<span key={`${match[1]}-${index}`}>{parts[match[1]]}</span>)
    last = index + match[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export interface ReviewError {
  message: string
  retryable: boolean
  /** `Date.now()` time from which a retry is allowed (`Retry-After`), or null. */
  until: number | null
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

/** The question about one spending spike (contract `review` card). Texts are the API's, in the request language. */
export const ReviewAsking = forwardRef<HTMLElement, AskingProps>(function ReviewAsking(
  { card, busy, error, onAnswer, onNotSure, onRetry, leaving },
  ref,
) {
  const { lang, t } = useSettings()
  const titleId = useId()
  // While the server asked to wait (Retry-After), a second tap on an answer would be a retry too.
  const waiting = useCountdown(error?.until ?? null) > 0
  const date = formatDate(card.date, lang)
  const purchaseRef = card.evidence_ref ?? card.amount.evidence_ref
  const seePurchase = card.actions.find((action) => action.type === 'open_evidence')?.label ?? t.reviewSeePurchase
  const question = card.question[lang]
  const tokens = new Set([...question.matchAll(TOKEN)].map((match) => match[1]))

  const dateChip = purchaseRef ? (
    <button
      type="button"
      onClick={() => openEvidence(purchaseRef)}
      aria-label={`${date}. ${seePurchase}`}
      className="relative inline-flex min-h-10 items-center rounded-pill border border-on-deep-muted/60 px-3 leading-7 align-baseline hover:border-on-deep after:absolute after:-inset-y-1 after:inset-x-0 after:content-['']"
    >
      {date}
    </button>
  ) : (
    date
  )
  // The core fills the question in (contract 0.2.2: "€1,080.42 at Home & Tech on 28 September 2026 —
  // needed, or your choice?"). Its amount, found as the API's own `display` string, becomes the
  // amount chip; `{{n1}}` / `{{date}}` tokens, if a question carries them, become chips too.
  const amountAt = tokens.has('n1') ? -1 : question.indexOf(card.amount.display)
  const inline = tokens.has('n1') || amountAt >= 0
  const amountChip = <NumberChip number={card.amount} size="lead" />
  const sentence = tokens.has('n1')
    ? fill(question, { n1: amountChip, date: dateChip })
    : [
        question.slice(0, amountAt),
        <span key="amount">{amountChip}</span>,
        ...fill(question.slice(amountAt + card.amount.display.length), { date: dateChip }),
      ]
  // What the sentence does not say itself: category and date (a filled-in question has them), merchant.
  const meta = [
    inline ? null : card.category,
    inline || tokens.has('date') ? null : date,
    card.merchant?.label ?? null,
  ].filter((part): part is string => Boolean(part))

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

      {inline ? (
        // The amount (and a date token) sit in the sentence as chips. On the 48px line each 40px chip
        // keeps a touch area of about 46px (measured), with no overlap between lines.
        <>
          <p className="mt-3 text-xl font-bold leading-12 text-on-deep">{sentence}</p>
          {meta.length > 0 && <p className="mt-1 text-sm text-on-deep-muted">{meta.join(' · ')}</p>}
        </>
      ) : (
        // A question without the amount (DESIGN.md order): the amount, then date, category and merchant,
        // then the question.
        <>
          <div className="mt-3">
            <NumberChip number={card.amount} size="lg" />
          </div>
          {meta.length > 0 && <p className="mt-1 text-sm text-on-deep-muted">{meta.join(' · ')}</p>}
          <p className="mt-3 text-lg font-semibold text-on-deep">{fill(question, { date: dateChip })}</p>
        </>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2">
        {card.options.map((option) => {
          const look = BASKETS[option.basket]
          const chosen = busy === option.basket
          return (
            <button
              key={option.basket}
              type="button"
              onClick={() => onAnswer(option.basket)}
              disabled={busy !== null || waiting}
              className={`flex min-h-[84px] flex-col items-center justify-center gap-1.5 rounded-lg border-t-4 bg-surface px-2 pb-3 pt-2 text-center text-base font-bold text-ink transition-transform duration-150 active:scale-[.97] disabled:cursor-wait ${look.line} ${
                chosen ? 'outline-3 outline-offset-2 outline-mint' : ''
              }`}
            >
              <span aria-hidden="true" className={`inline-flex size-9 items-center justify-center rounded-md text-lg ${look.tint}`}>
                {look.icon}
              </span>
              {option.label[lang]}
            </button>
          )
        })}
      </div>

      {error && (
        // Only the message is the alert; the countdown sits outside it, so a screen reader does not
        // announce every second of it.
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-danger-tint px-3 py-2 text-sm text-ink">
          <span role="alert" className="flex-1">
            {error.message}
          </span>
          {error.retryable && (
            <RetryButton
              onRetry={onRetry}
              until={error.until}
              className="min-h-11 font-semibold text-danger underline underline-offset-4"
            />
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
  const { lang } = useSettings()
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
          {option?.label[lang]}
        </h2>
      </div>
      {option && <p className="mt-2 text-base text-on-deep-muted">{option.effect[lang]}</p>}
    </section>
  )
})
