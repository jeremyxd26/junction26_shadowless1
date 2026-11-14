// The explanation of a bill (#330, reference screen C6b), from a POST /api/bill/explain response:
// - how it compares with the usual amount (when the payee matched a regular bill) and its basket;
// - safe to spend before and after the bill;
// - the bill's terms (viitenumero, eräpäivä, virtuaaliviivakoodi, viivästyskorko) as dotted
//   buttons that open a short sheet with the response's glossary text.
// Every number is a NumberChip with the API's `display`; every sentence of the response is shown as
// plain text, never split into chips. The match sentence is the step's heading (BillFlow).
import { useCallback, useState, type ReactNode } from 'react'
import type { BillExplainResponse, BillGlossaryEntry, BillSafeToSpend } from '../../api/billTypes.ts'
import type { Comparison } from '../../api/types.ts'
import { BASKETS } from '../../lib/baskets.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { chatStrings } from '../../lib/chatStrings.ts'
import { useSettings } from '../../lib/settings.ts'
import { useEstimateToggle } from '../../lib/useEstimateToggle.ts'
import { CARD_TITLE, CardShell } from '../cards.tsx'
import { EstimateBadge, EstimateNote } from '../EstimateBadge.tsx'
import { NumberChip } from '../NumberChip.tsx'
import { BillForecast } from './BillForecast.tsx'
import { TermSheet } from './TermSheet.tsx'

/** --color-up and --color-down follow brand and warning; an arrow and words, never colour alone. */
const TONE: Record<Comparison['tone'], { text: string; arrow: string }> = {
  worse: { text: 'text-warning', arrow: '▲' },
  better: { text: 'text-brand', arrow: '▼' },
  neutral: { text: 'text-muted', arrow: '•' },
}

interface Props {
  response: BillExplainResponse
  /** Rendered between safe to spend and the terms: the warning signs and Add to payments (#331). */
  children?: ReactNode
  /** Asks a question in the thread: the forecast's ask chip (`not_covered`). */
  onAsk: (question: string) => void
}

export function BillExplanationCard({ response, children, onAsk }: Props) {
  const [term, setTerm] = useState<BillGlossaryEntry | null>(null)
  const closeTerm = useCallback(() => setTerm(null), [])
  return (
    <div className="flex flex-col gap-3">
      <ComparisonCard response={response} />
      {response.safe_to_spend && <SafeToSpendCard safe={response.safe_to_spend} />}
      {/* Contract 0.3.4: missing or null from an older API, then nothing and no gap. */}
      {response.forecast && <BillForecast forecast={response.forecast} onAsk={onAsk} />}
      {children}
      <TermsCard response={response} onTerm={setTerm} />
      {term && <TermSheet label={term.label} text={term.text} onClose={closeTerm} />}
    </div>
  )
}

function ComparisonCard({ response }: { response: BillExplainResponse }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const { bill, comparison, basket } = response
  const look = BASKETS[basket.key] ?? BASKETS.unexpected_necessities
  return (
    <CardShell>
      {/* With large text the fact label wraps inside its own column instead of running past the card. */}
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-[min(6rem,100%)] flex-1 basis-0">
          <h3 className={CARD_TITLE}>{comparison ? s.vsUsualTitle : s.thisBillTitle}</h3>
          {comparison && <p className="text-sm text-muted">{comparison.label}</p>}
        </div>
        {comparison && (
          <span className="ml-auto max-w-[45%] shrink-0 pt-0.5 text-right text-xs break-words hyphens-auto text-muted">
            {chatStrings(lang).fact}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-3">
        <div className="flex flex-col items-start gap-1">
          <span className="text-sm text-muted">{bill.amount.label}</span>
          <NumberChip number={bill.amount} size="lg" />
        </div>
        {comparison && (
          <div className="flex flex-col items-start gap-1">
            <span className="text-sm text-muted">{comparison.baseline.label}</span>
            <NumberChip number={comparison.baseline} size="lg" tone="neutral" />
          </div>
        )}
      </div>

      {comparison && (
        <p className={`mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm leading-8 ${TONE[comparison.tone]?.text ?? TONE.neutral.text}`}>
          <span aria-hidden="true">{TONE[comparison.tone]?.arrow ?? TONE.neutral.arrow}</span>
          <NumberChip number={comparison.change} size="inline" tone="neutral" />
          {comparison.change_pct && <NumberChip number={comparison.change_pct} size="inline" tone="neutral" />}
          <span className="font-semibold">{s.vsUsualWord[comparison.tone] ?? ''}</span>
        </p>
      )}

      <div className="mt-3 flex gap-3 border-t border-line pt-3">
        <span
          aria-hidden="true"
          className={`inline-flex size-10 shrink-0 items-center justify-center rounded-md text-lg ${look.tint} ${look.color}`}
        >
          {look.icon}
        </span>
        {/* A size container, so the text hyphenates only when the column is narrow in rem (large
            text); at normal size it is about 16rem and its line breaks stay as they were (#541). */}
        <div className="@container min-w-0 flex-1">
          <p className={`flex min-h-10 items-center font-semibold ${look.color}`}>
            <span className="min-w-0 break-words hyphens-auto">{basket.label}</span>
          </p>
          <p className="text-sm text-ink-2 break-words @max-[10rem]:hyphens-auto">{basket.text}</p>
        </div>
      </div>
    </CardShell>
  )
}

/** Before → after, as chips; after a payday only the "before" chip, because nothing changes. */
function SafeToSpendCard({ safe }: { safe: BillSafeToSpend }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const after = safe.effect === 'after_payday' ? null : safe.after
  // Controlled, so the open estimate text runs full width under the header, not beside the title.
  const estimate = useEstimateToggle()
  return (
    <CardShell>
      {/* With large text the Estimate badge moves under the title instead of squeezing it (#493). */}
      <div className="flex flex-wrap items-start justify-between gap-x-3">
        <h3 className={`min-w-[min(9rem,100%)] flex-1 basis-0 pt-2.5 ${CARD_TITLE}`}>{s.safeTitle}</h3>
        <EstimateBadge estimate={s.estimate} control={estimate.control} />
      </div>
      {estimate.open && <EstimateNote estimate={s.estimate} id={estimate.id} />}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="sr-only">{s.before}</span>
        <NumberChip number={safe.before} />
        {after && (
          <>
            <span aria-hidden="true" className="text-muted">
              →
            </span>
            <span className="sr-only">{s.after}</span>
            <NumberChip number={after} />
          </>
        )}
      </div>
      <p className="mt-2 text-base text-ink-2">{safe.text}</p>
    </CardShell>
  )
}

/** The bill's details with its terms as dotted buttons, keyed by `glossary[].term`. */
function TermsCard({ response, onTerm }: { response: BillExplainResponse; onTerm: (entry: BillGlossaryEntry) => void }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const { bill, glossary } = response
  const entry = (key: string) => glossary.find((item) => item.term === key) ?? null
  const rows: { key: string; label: string; term: BillGlossaryEntry | null; value: string }[] = [
    { key: 'payee', label: s.fieldLabels.payee, term: null, value: bill.payee ?? s.noPayee },
    { key: 'reference', label: s.fieldLabels.reference, term: entry('reference_number'), value: bill.reference },
    { key: 'due_date', label: s.fieldLabels.due_date, term: entry('due_date'), value: bill.amount.period.label },
    {
      key: 'barcode',
      label: s.fieldLabels.barcode,
      term: entry('virtual_barcode'),
      value: bill.source === 'barcode' ? s.fromBarcode : s.typedDetails,
    },
    { key: 'late', label: s.latePayment, term: entry('late_payment_interest'), value: s.latePaymentHint },
  ]
  return (
    <CardShell>
      <h3 className={CARD_TITLE}>{s.detailsTitle}</h3>
      <p className="text-sm text-muted">{s.termsHint}</p>
      <ul className="mt-1 flex flex-col divide-y divide-line">
        {rows.map((row) => (
          <li key={row.key} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-1.5">
            {/* At least 9rem, or the whole row when that is narrower; a longer label wraps inside it, and
                the value then moves to the next line. */}
            <span className="max-w-full min-w-[min(9rem,100%)] shrink-0 text-sm [overflow-wrap:anywhere]">
              {row.term ? (
                <button
                  type="button"
                  onClick={() => row.term && onTerm(row.term)}
                  aria-haspopup="dialog"
                  className="inline-flex min-h-11 items-center text-left font-semibold text-brand underline decoration-brand decoration-dotted decoration-2 underline-offset-4"
                >
                  {row.label}
                </button>
              ) : (
                <span className="inline-flex min-h-11 items-center text-muted">{row.label}</span>
              )}
            </span>
            <span className="min-w-0 flex-1 basis-32 text-base break-words text-ink">{row.value}</span>
          </li>
        ))}
      </ul>
    </CardShell>
  )
}
