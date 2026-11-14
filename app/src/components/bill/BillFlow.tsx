// The bill flow (Lasku): one container that runs the steps and makes the calls.
// gallery → reading (POST /api/bill/read) → fields → explaining (POST /api/bill/explain) → explanation.
// The fields card (#329) and the explanation card (#330) plug into the `fields` and `explanation`
// steps; until then those steps show a plain read-only preview.
import { useEffect, useReducer } from 'react'
import { billApi } from '../../api/bill.ts'
import type { BillReadFieldKey, BillReadResponse } from '../../api/billTypes.ts'
import { ApiError } from '../../api/errors.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { strings } from '../../lib/i18n.ts'
import { useSettings } from '../../lib/settings.ts'
import { CARD_TITLE, CardShell } from '../cards.tsx'
import { ErrorBlock, LoadingBlock } from '../States.tsx'
import { BillGallery } from './BillGallery.tsx'
import { flowReducer, initialFlow, type FlowError } from './billFlowState.ts'

interface Props {
  /** Called when the user is finished with an explained bill. */
  onDone?: () => void
}

function toFlowError(error: unknown, fallback: string): FlowError {
  if (error instanceof ApiError) return { message: error.message, retryable: error.retryable }
  return { message: fallback, retryable: true }
}

export function BillFlow({ onDone }: Props) {
  const { lang, customerId } = useSettings()
  const [state, dispatch] = useReducer(flowReducer, initialFlow)
  const s = billStrings(lang)
  const t = strings(lang)

  const readingId = state.step === 'reading' ? state.sampleId : null
  useEffect(() => {
    if (readingId === null) return
    billApi.read({ customer_id: customerId ?? '', language: lang, sample_id: readingId }).then(
      (reading) => dispatch({ type: 'read_ok', sampleId: readingId, reading }),
      (error: unknown) => {
        if (error instanceof ApiError && error.code === 'model_unavailable') {
          dispatch({ type: 'read_unavailable', sampleId: readingId })
        } else {
          dispatch({ type: 'read_failed', sampleId: readingId, error: toFlowError(error, t.errorRetry) })
        }
      },
    )
    // The reducer ignores an answer for a sample the user has already left.
  }, [readingId, customerId, lang, t.errorRetry])

  const request = state.step === 'explaining' ? state.request : null
  useEffect(() => {
    if (request === null) return
    let cancelled = false
    billApi.explain(request).then(
      (response) => !cancelled && dispatch({ type: 'explain_ok', response }),
      (error: unknown) => !cancelled && dispatch({ type: 'explain_failed', error: toFlowError(error, t.errorRetry) }),
    )
    return () => {
      cancelled = true
    }
  }, [request, t.errorRetry])

  const back = () => dispatch({ type: 'back' })

  switch (state.step) {
    case 'gallery': {
      const retrySample = state.lastSampleId
      return (
        <div className="flex flex-col gap-3">
          {state.error && (
            <ErrorBlock
              message={state.error.message}
              onRetry={state.error.retryable && retrySample ? () => dispatch({ type: 'pick', sampleId: retrySample }) : undefined}
            />
          )}
          <BillGallery onPick={(sampleId) => dispatch({ type: 'pick', sampleId })} />
        </div>
      )
    }
    case 'reading':
      return (
        <CardShell>
          <p className="mb-3 text-base text-ink-2">{s.reading}</p>
          <LoadingBlock lines={5} />
        </CardShell>
      )
    case 'fields':
    case 'explaining':
      return (
        <div className="flex flex-col gap-3">
          {state.step === 'fields' && state.error && <ErrorBlock message={state.error.message} />}
          <ReadingPreview reading={state.reading} />
          {state.step === 'explaining' && <p className="text-sm text-muted">{s.explaining}</p>}
          <BackButton label={s.backToSamples} onClick={back} />
        </div>
      )
    case 'explanation':
      return (
        <div className="flex flex-col gap-3">
          <CardShell>
            <p className="text-base text-ink-2">{state.response.match.text}</p>
          </CardShell>
          <BackButton
            label={s.done}
            onClick={() => {
              back()
              onDone?.()
            }}
          />
        </div>
      )
  }
}

const FIELD_ORDER: BillReadFieldKey[] = ['payee', 'iban', 'reference', 'amount', 'due_date', 'barcode']

/**
 * What Sentti read, field by field, each marked checked or "Is this right?". Read-only: the
 * editable fields card with Confirm replaces it (#329). `reading: null` is the typed fallback.
 */
function ReadingPreview({ reading }: { reading: BillReadResponse | null }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  return (
    <CardShell>
      <h2 className={CARD_TITLE}>{reading ? s.confirmTitle : s.typeTitle}</h2>
      <dl className="mt-2 flex flex-col divide-y divide-line">
        {FIELD_ORDER.map((key) => {
          const read = reading?.fields[key] ?? null
          if (key === 'barcode' && !read) return null
          return (
            <div key={key} className="flex min-h-14 flex-col justify-center gap-0.5 py-2">
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <dt className="text-sm text-muted">{s.fieldLabels[key]}</dt>
                <StatusMark checked={read?.status === 'checked'} />
              </div>
              <dd className={`text-base text-ink ${key === 'barcode' ? 'font-mono text-sm break-all' : ''}`}>
                {read ? read.display : reading ? <span className="text-muted">{s.notFound}</span> : null}
              </dd>
              {read?.note && <dd className="text-sm text-ink-2">{read.note}</dd>}
            </div>
          )
        })}
      </dl>
    </CardShell>
  )
}

/** Checked (a mark and a word) or "Is this right?"; never colour alone. */
function StatusMark({ checked }: { checked: boolean }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  return checked ? (
    <span className="inline-flex items-center gap-1 rounded-pill bg-mint-tint px-2.5 py-0.5 text-xs font-semibold text-brand">
      <span aria-hidden="true">✓</span>
      {s.checked}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-pill bg-waiting-tint px-2.5 py-0.5 text-xs font-semibold text-waiting">
      <span aria-hidden="true">?</span>
      {s.isThisRight}
    </span>
  )
}

function BackButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex min-h-11 items-center justify-center self-start rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
    >
      {label}
    </button>
  )
}
