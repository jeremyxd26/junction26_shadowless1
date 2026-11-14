// The fields card (#329, reference screen C6a): what Sentti read from a sample bill, for the user
// to confirm before anything is explained.
// - Review (a reading): each field shows the read `display` with "Checked" or "Is this right?";
//   a field the reader did not find is an empty input marked "Is this right?". "Looks right,
//   explain it" confirms; "Edit details" turns every field into an input prefilled with `value`.
// - Typed fallback (no reading, the reader is unavailable): empty inputs without marks.
// Confirm builds the explain request with lib/billRequest.ts. Nothing here formats a number, and
// nothing typed leaves this component except in the request handed to the flow.
import { useId, useState } from 'react'
import type { BillExplainRequest, BillReadField, BillReadResponse } from '../../api/billTypes.ts'
import { buildExplainRequest, FIELD_KEYS, initialInputs, type FieldInputs } from '../../lib/billRequest.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { useSettings } from '../../lib/settings.ts'
import { CARD_TITLE, CardShell } from '../cards.tsx'
import { ErrorBlock } from '../States.tsx'
import type { FlowError } from './billFlowState.ts'

interface Props {
  reading: BillReadResponse | null
  /** True while the explanation is on its way: the buttons wait. */
  busy: boolean
  /**
   * The last explain error (already localised). "Try again", offered only when it is retryable,
   * confirms again with the fields as they are now, so edits made after the error are sent.
   */
  error: FlowError | null
  onConfirm: (request: BillExplainRequest) => void
}

const INPUT =
  'min-h-11 w-full rounded-md border border-line-strong bg-surface px-3 text-base text-ink aria-invalid:border-danger'
const PRIMARY =
  'inline-flex min-h-12 w-full items-center justify-center rounded-pill bg-mint px-5 text-base font-bold text-ink hover:bg-mint-hover disabled:cursor-wait disabled:opacity-70'
const SECONDARY =
  'inline-flex min-h-12 w-full items-center justify-center rounded-pill border border-line-strong bg-surface px-5 text-base font-semibold text-ink-2 hover:bg-sunken'

export function BillFieldsCard({ reading, busy, error, onConfirm }: Props) {
  const { lang, customerId } = useSettings()
  const s = billStrings(lang)
  const id = useId()
  const [initial] = useState<FieldInputs>(() => initialInputs(reading))
  const [inputs, setInputs] = useState<FieldInputs>(initial)
  const [editingAll, setEditingAll] = useState(reading === null)
  const [attempted, setAttempted] = useState(false)

  const result = buildExplainRequest({ customerId, language: lang, reading, inputs })
  const problems = attempted && !result.ok ? result.problems : {}
  const missingCustomer = attempted && !result.ok && result.missingCustomer

  const confirm = () => {
    setAttempted(true)
    if (result.ok && !busy) onConfirm(result.request)
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <ErrorBlock message={error.message} onRetry={error.retryable ? confirm : undefined} />}
      <CardShell>
        <h3 className={CARD_TITLE}>{s.cardTitle}</h3>
        {reading && <p className="text-sm text-muted">{s.cardSubtitle}</p>}
        <form
          id={`${id}-form`}
          noValidate
          autoComplete="off"
          className="mt-1"
          onSubmit={(event) => {
            event.preventDefault()
            confirm()
          }}
        >
          <ul className="flex flex-col divide-y divide-line">
            {FIELD_KEYS.map((key) => {
              const read = reading?.fields[key] ?? null
              const label = s.fieldLabels[key]
              // The mark describes what was read; once the user changes the value it no longer applies.
              const mark = reading && inputs[key] === initial[key] ? <ReadMark read={read} /> : null
              if (read && !editingAll) {
                return (
                  <li key={key} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2.5">
                    <span className="w-20 shrink-0 text-sm text-muted">{label}</span>
                    <span className="min-w-0 flex-1 basis-20 text-base font-semibold break-words text-ink">{read.display}</span>
                    {mark}
                  </li>
                )
              }
              const inputId = `${id}-${key}`
              const helpId = `${id}-${key}-help`
              const problem = problems[key]
              return (
                <li key={key} className="flex flex-col gap-1.5 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <label htmlFor={inputId} className="text-sm font-semibold text-ink">
                      {label}
                    </label>
                    {mark}
                  </div>
                  <input
                    id={inputId}
                    name={key}
                    type={key === 'due_date' ? 'date' : 'text'}
                    inputMode={key === 'amount' ? 'decimal' : undefined}
                    autoCapitalize={key === 'iban' || key === 'reference' ? 'characters' : undefined}
                    autoCorrect="off"
                    spellCheck={false}
                    value={inputs[key]}
                    onChange={(event) => setInputs((current) => ({ ...current, [key]: event.target.value }))}
                    aria-invalid={problem ? true : undefined}
                    aria-describedby={helpId}
                    className={INPUT}
                  />
                  <div id={helpId} className="flex flex-col gap-1">
                    {key === 'amount' && <p className="text-sm text-muted">{s.amountHint}</p>}
                    {read?.note && <p className="text-sm text-ink-2">{read.note}</p>}
                    {problem && <p className="text-sm font-semibold text-danger">{s.problems[problem]}</p>}
                  </div>
                </li>
              )
            })}
          </ul>
          {editingAll && reading?.fields.barcode && <p className="mt-2 text-sm text-muted">{s.barcodeKept}</p>}
        </form>
      </CardShell>

      {reading && <p className="rounded-lg bg-sunken p-3 text-sm text-ink-2">{s.checkedMeans}</p>}
      {/* A read note on a read-only field is shown here, so it is never hidden. */}
      {!editingAll &&
        FIELD_KEYS.map((key) => {
          const read = reading?.fields[key]
          return read?.note ? (
            <p key={key} className="text-sm text-ink-2">
              <span className="font-semibold">{s.fieldLabels[key]}:</span> {read.note}
            </p>
          ) : null
        })}
      {missingCustomer && (
        <p role="alert" className="text-sm font-semibold text-danger">
          {s.noCustomer}
        </p>
      )}

      <button type="submit" form={`${id}-form`} disabled={busy} aria-busy={busy} className={PRIMARY}>
        {busy ? s.explaining : editingAll ? s.confirm : s.looksRight}
      </button>
      {!editingAll && (
        <button type="button" onClick={() => setEditingAll(true)} className={SECONDARY}>
          {s.editDetails}
        </button>
      )}
    </div>
  )
}

/** "Checked" (an icon and a word) or "Is this right?" for an unchecked or missing field. */
function ReadMark({ read }: { read: BillReadField | null }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  return read?.status === 'checked' ? (
    <span className="inline-flex shrink-0 items-center gap-1 text-sm font-bold whitespace-nowrap text-brand">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="size-[1.25em]" fill="currentColor">
        <path d="M10 1.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm4.03 6.28-4.75 5.5a.75.75 0 0 1-1.1.04l-2.25-2.25a.75.75 0 1 1 1.06-1.06l1.68 1.68 4.2-4.87a.75.75 0 1 1 1.16.96Z" />
      </svg>
      {s.checked}
    </span>
  ) : (
    <span className="inline-flex shrink-0 items-center rounded-pill bg-warning-tint px-2.5 py-0.5 text-sm font-bold whitespace-nowrap text-warning">
      {s.isThisRight}
    </span>
  )
}
