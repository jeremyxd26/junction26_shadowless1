// The bill flow (Lasku): one container that runs the steps and makes the calls.
// gallery → reading (POST /api/bill/read) → fields → explaining (POST /api/bill/explain) → explanation.
// The `fields` step is the fields card (#329); the `explanation` step is the explanation (#330),
// headed by the response's match sentence.
import { useEffect, useReducer } from 'react'
import { billApi } from '../../api/bill.ts'
import { ApiError } from '../../api/errors.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { strings } from '../../lib/i18n.ts'
import { useSettings } from '../../lib/settings.ts'
import { CardShell } from '../cards.tsx'
import { ErrorBlock, LoadingBlock } from '../States.tsx'
import { AddToPayments } from './AddToPayments.tsx'
import { BillExplanationCard } from './BillExplanationCard.tsx'
import { BillFieldsCard } from './BillFieldsCard.tsx'
import { BillGallery } from './BillGallery.tsx'
import { BillSignals } from './BillSignals.tsx'
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
    // Wait for the persona: a read without a customer would be refused by the core.
    if (readingId === null || !customerId) return
    billApi.read({ customer_id: customerId, language: lang, sample_id: readingId }).then(
      (reading) => dispatch({ type: 'read_ok', sampleId: readingId, reading }),
      (error: unknown) => {
        if (error instanceof ApiError && error.code === 'model_unavailable') {
          dispatch({ type: 'read_unavailable', sampleId: readingId, message: error.message })
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
      // One element for both steps, so the user's edits survive a failed explanation.
      return (
        <div className="flex flex-col gap-3">
          <h2 className="text-card-title font-bold text-brand">{state.reading ? s.confirmTitle : s.typeTitle}</h2>
          {state.notice && <p className="rounded-lg bg-sunken p-3 text-base text-ink-2">{state.notice}</p>}
          {state.step === 'fields' && state.error && (
            // A 422 `invalid_bill` is not retryable: its message asks to compare or edit the fields.
            <ErrorBlock
              message={state.error.message}
              onRetry={state.error.retryable && state.failed ? () => dispatch({ type: 'retry_explain' }) : undefined}
            />
          )}
          <BillFieldsCard
            key={state.sampleId ?? 'typed'}
            reading={state.reading}
            busy={state.step === 'explaining'}
            onConfirm={(request) => dispatch({ type: 'confirm', request })}
          />
          {state.step === 'explaining' && (
            <CardShell>
              <p className="mb-3 text-base text-ink-2">{s.explaining}</p>
              <LoadingBlock lines={5} />
            </CardShell>
          )}
          <BackButton label={s.backToSamples} onClick={back} />
        </div>
      )
    case 'explanation':
      return (
        <div className="flex flex-col gap-3">
          <h2 className="text-card-title font-bold text-ink">{state.response.match.text}</h2>
          <BillExplanationCard response={state.response}>
            <BillSignals signals={state.response.signals} />
            <AddToPayments response={state.response} />
          </BillExplanationCard>
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
