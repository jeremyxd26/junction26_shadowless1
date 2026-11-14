import { forwardRef, useId, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { BasketKey, ReviewCard as ReviewCardData } from '../api/types.ts'
import { BASKETS } from '../lib/baskets.ts'
import { formatDate } from '../lib/i18n.ts'
import { openEvidence } from '../lib/url.ts'
import { useCountdown } from '../lib/useCountdown.ts'
import { useSettings } from '../lib/settings.ts'
import { BottomSheet } from './BottomSheet.tsx'
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

/** The purchase's evidence and its link label ("See the purchase"). */
function purchaseOf(card: ReviewCardData, fallback: string) {
  const ref = card.evidence_ref ?? card.amount.evidence_ref
  const label = card.actions.find((action) => action.type === 'open_evidence')?.label ?? fallback
  return { ref, label }
}

/** Category, date and merchant: the purchase's facts in one line. */
function factsOf(card: ReviewCardData, date: string): string {
  return [card.category, date, card.merchant?.label ?? null].filter((part): part is string => Boolean(part)).join(' · ')
}

/**
 * The question as the API sends it, in the request language. The core fills it in (contract
 * 0.2.2: "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?"); its amount,
 * found as the API's own `display` string, becomes the amount chip, and `{{n1}}` / `{{date}}`
 * tokens, if a question carries them, become chips too. A question that does not carry the
 * amount gets the amount chip at its start: the amount is shown once, with no separate line.
 * `compact` (after the answer, as context): 16px text and the smaller inline chip.
 */
function QuestionText({ card, compact = false }: { card: ReviewCardData; compact?: boolean }) {
  const { lang, t } = useSettings()
  const date = formatDate(card.date, lang)
  const purchase = purchaseOf(card, t.reviewSeePurchase)
  const question = card.question[lang]
  const tokens = new Set([...question.matchAll(TOKEN)].map((match) => match[1]))
  const dateChip = purchase.ref ? (
    <button
      type="button"
      onClick={() => purchase.ref && openEvidence(purchase.ref)}
      aria-label={`${date}. ${purchase.label}`}
      className="relative inline-flex min-h-9 items-center rounded-pill border border-on-deep-muted/60 px-2.5 leading-6 align-baseline hover:border-on-deep after:absolute after:-inset-y-1 after:inset-x-0 after:content-['']"
    >
      {date}
    </button>
  ) : (
    date
  )
  const amountChip = <NumberChip number={card.amount} size={compact ? 'inline' : 'lead'} />
  const amountAt = tokens.has('n1') ? -1 : question.indexOf(card.amount.display)
  const sentence = tokens.has('n1')
    ? fill(question, { n1: amountChip, date: dateChip })
    : amountAt >= 0
      ? [
          question.slice(0, amountAt),
          <span key="amount">{amountChip}</span>,
          ...fill(question.slice(amountAt + card.amount.display.length), { date: dateChip }),
        ]
      : [<span key="amount">{amountChip}</span>, ' ', ...fill(question, { date: dateChip })]
  // A normal line height (about 1.3); the chip's line grows to fit it, and its ::after keeps the
  // touch area at 44px.
  return compact ? (
    <p className="mt-2 text-base font-semibold leading-[22px] text-on-deep-muted">{sentence}</p>
  ) : (
    <p className="mt-2 text-xl font-bold leading-[26px] text-on-deep">{sentence}</p>
  )
}

function InfoGlyph() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
    </svg>
  )
}

/** Why Sentti asks (`why`) and the purchase's facts, in a small sheet: no paragraph on the card. */
function WhySheet({ card, onClose }: { card: ReviewCardData; onClose: () => void }) {
  const { lang, t } = useSettings()
  const purchase = purchaseOf(card, t.reviewSeePurchase)
  // In a portal: the card animates with a transform, which would pin a fixed sheet to it.
  return createPortal(
    <BottomSheet title={t.reviewWhy} onClose={onClose}>
      <p className="text-base text-ink-2">{card.why}</p>
      <p className="mt-3 text-sm text-muted">{factsOf(card, formatDate(card.date, lang))}</p>
      {purchase.ref && (
        <button
          type="button"
          onClick={() => {
            onClose()
            if (purchase.ref) openEvidence(purchase.ref)
          }}
          className="mt-4 inline-flex min-h-11 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
        >
          {purchase.label}
        </button>
      )}
    </BottomSheet>,
    document.body,
  )
}

/** "? Sentti asks", then the card's own controls on the right. */
function AsksHeader({ titleId, children }: { titleId: string; children?: ReactNode }) {
  const { t } = useSettings()
  return (
    <div className="flex flex-wrap items-center gap-x-3">
      <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-pill bg-mint text-lg font-bold text-ink">
        ?
      </span>
      {/* No min-w-0: the title keeps its longest word, so on a narrow screen the buttons wrap below. */}
      <h2 id={titleId} className="flex-1 text-base font-semibold text-on-deep">
        {t.reviewAsks}
      </h2>
      {children}
    </div>
  )
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

/**
 * The question about one spending spike (contract `review` card), compact for the opening turn
 * (#310 decision): the question with its amount chip and two answer buttons; `why` behind ⓘ.
 */
export const ReviewAsking = forwardRef<HTMLElement, AskingProps>(function ReviewAsking(
  { card, busy, error, onAnswer, onNotSure, onRetry, leaving },
  ref,
) {
  const { lang, t } = useSettings()
  const titleId = useId()
  const [whyOpen, setWhyOpen] = useState(false)
  // While the server asked to wait (Retry-After), a second tap on an answer would be a retry too.
  const waiting = useCountdown(error?.until ?? null) > 0

  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={titleId}
      aria-busy={busy !== null}
      data-review-card={card.tx_ref}
      data-opening-part="review"
      className={`${SURFACE} ${leaving ? 'card-leave' : 'card-enter'}`}
    >
      <AsksHeader titleId={titleId}>
        {/* Client only: closes the card; the purchase keeps waiting for an answer. */}
        <button
          type="button"
          onClick={onNotSure}
          disabled={busy !== null}
          className="min-h-11 px-1 text-sm font-semibold text-on-deep-muted underline underline-offset-4 hover:text-on-deep"
        >
          {t.reviewNotSure}
        </button>
        <button
          type="button"
          onClick={() => setWhyOpen(true)}
          aria-label={t.reviewWhy}
          className="-mr-2 inline-flex size-11 shrink-0 items-center justify-center rounded-pill text-on-deep-muted hover:text-on-deep"
        >
          <InfoGlyph />
        </button>
      </AsksHeader>

      <QuestionText card={card} />

      {/* Two columns while each is at least 9rem wide, else one; labels wrap inside the buttons. */}
      <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(9rem,100%),1fr))] gap-2">
        {card.options.map((option) => {
          const look = BASKETS[option.basket]
          const chosen = busy === option.basket
          return (
            <button
              key={option.basket}
              type="button"
              onClick={() => onAnswer(option.basket)}
              disabled={busy !== null || waiting}
              className={`flex min-h-12 min-w-0 items-center gap-1.5 rounded-lg border-l-4 bg-surface py-1.5 pl-1.5 pr-2 text-left text-base font-bold leading-5 text-ink transition-transform duration-150 active:scale-[.97] disabled:cursor-wait ${look.line} ${
                chosen ? 'outline-3 outline-offset-2 outline-mint' : ''
              }`}
            >
              {/* A 28px tile leaves "Välttämätön" its whole width at 375 px. With large text the label
                  hyphenates in the UI language ("Vält-tä-mä-tön", #541); breaking without a hyphen is
                  only the last resort, where no hyphenation point fits. */}
              <span aria-hidden="true" className={`inline-flex size-7 shrink-0 items-center justify-center rounded-md text-base ${look.tint}`}>
                {look.icon}
              </span>
              <span lang={lang} className="min-w-0 break-words hyphens-auto">
                {option.label[lang]}
              </span>
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

      {whyOpen && <WhySheet card={card} onClose={() => setWhyOpen(false)} />}
    </section>
  )
})

interface AnsweredProps {
  card: ReviewCardData
  basket: BasketKey
  /** While the answer can be undone (#315): a 44 px Undo in the card, next to the toast's. */
  onUndo?: () => void
}

/**
 * After the tap: the header, the question and the chosen answer (reference 2-after-needed). What
 * the answer does is Sentti's reply under the card (#317), never a line on the card.
 */
export const ReviewAnswered = forwardRef<HTMLElement, AnsweredProps>(function ReviewAnswered(
  { card, basket, onUndo },
  ref,
) {
  const { lang, t } = useSettings()
  const titleId = useId()
  const option = card.options.find((candidate) => candidate.basket === basket)
  const look = BASKETS[basket]
  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-review-card={card.tx_ref}
      data-opening-part="review"
      className={`${SURFACE} card-enter`}
    >
      <AsksHeader titleId={titleId}>
        {onUndo && (
          <button
            type="button"
            onClick={onUndo}
            className="min-h-11 min-w-11 px-1 text-sm font-semibold text-mint underline underline-offset-4 hover:text-on-deep"
          >
            {t.undo}
          </button>
        )}
      </AsksHeader>
      <QuestionText card={card} compact />
      <p className="mt-2 flex items-center gap-2 text-base font-bold text-on-deep">
        <span aria-hidden="true" className="inline-flex size-6 shrink-0 items-center justify-center rounded-pill bg-mint text-ink">
          <Check className="size-4" />
        </span>
        <span aria-hidden="true">{look?.icon}</span>
        {option?.label[lang]}
      </p>
    </section>
  )
})
