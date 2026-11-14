// Builds the POST /api/bill/explain request (contract section 11.1) from what the user confirmed.
// Pure: no React, no network. It never formats a number: the amount is the typed string with a
// comma replaced by a dot, nothing else (no parseFloat, no toFixed).
import type { BillExplainRequest, BillFields, BillReadResponse } from '../api/billTypes.ts'
import type { Language } from '../api/types.ts'

export type FieldKey = keyof BillFields

export const FIELD_KEYS: FieldKey[] = ['payee', 'iban', 'reference', 'amount', 'due_date']

/** The inputs as strings, exactly as the user sees them. */
export type FieldInputs = Record<FieldKey, string>

/** Why a field cannot be sent; the form shows the app's own sentence for each. */
export type FieldProblem = 'required' | 'too_long' | 'amount_format' | 'amount_range' | 'date_format'

export type BuildResult =
  | { ok: true; request: BillExplainRequest }
  | { ok: false; problems: Partial<Record<FieldKey, FieldProblem>>; missingCustomer: boolean }

/** Contract limits (section 11.1). */
export const LIMITS = { payee: 70, iban: 42, reference: 35, barcode: 80 } as const

/** What the inputs start with: the read `value`, or empty when the field was not read. */
export function initialInputs(reading: BillReadResponse | null): FieldInputs {
  const inputs = {} as FieldInputs
  for (const key of FIELD_KEYS) inputs[key] = reading?.fields[key]?.value ?? ''
  return inputs
}

const AMOUNT = /^\d{1,6}([.,]\d{1,2})?$/
const DATE = /^\d{4}-\d{2}-\d{2}$/

/** The amount as the contract wants it: a dot, nothing reformatted. Null when it does not fit. */
export function normaliseAmount(typed: string): { amount: string } | { problem: FieldProblem } {
  const text = typed.trim()
  if (text === '') return { problem: 'required' }
  if (!AMOUNT.test(text)) return { problem: 'amount_format' }
  const amount = text.replace(',', '.')
  // More than 0 and at most 100000.00, decided on the digits, not on a parsed float.
  const [whole, fraction = ''] = amount.split('.')
  if (!/[1-9]/.test(amount)) return { problem: 'amount_range' }
  if (whole.length === 6 && (whole !== '100000' || /[1-9]/.test(fraction))) return { problem: 'amount_range' }
  return { amount }
}

function checkText(value: string, limit: number): FieldProblem | null {
  if (value === '') return 'required'
  return value.length > limit ? 'too_long' : null
}

interface BuildInput {
  customerId: string | null
  language: Language
  reading: BillReadResponse | null
  inputs: FieldInputs
}

/**
 * The confirmed barcode with the payee beside it when the reading has a barcode and none of IBAN,
 * reference, amount and due date was edited; otherwise the five fields. `payee` is never sent
 * beside `fields`, and an empty text is sent as null, never "".
 */
export function buildExplainRequest({ customerId, language, reading, inputs }: BuildInput): BuildResult {
  const initial = initialInputs(reading)
  const edited = (key: FieldKey) => inputs[key] !== initial[key]
  const payee = inputs.payee.trim()
  const missingCustomer = !customerId
  const problems: Partial<Record<FieldKey, FieldProblem>> = {}

  const barcode = reading?.fields.barcode?.value ?? null
  const useBarcode =
    barcode !== null && barcode.length <= LIMITS.barcode && !(['iban', 'reference', 'amount', 'due_date'] as const).some(edited)

  if (useBarcode) {
    if (payee.length > LIMITS.payee) problems.payee = 'too_long'
    if (!customerId || Object.keys(problems).length > 0) return { ok: false, problems, missingCustomer }
    return {
      ok: true,
      request: { customer_id: customerId, language, barcode, payee: payee === '' ? null : payee, fields: null },
    }
  }

  const iban = inputs.iban.trim()
  const reference = inputs.reference.trim()
  const dueDate = inputs.due_date.trim()
  const payeeProblem = checkText(payee, LIMITS.payee)
  const ibanProblem = checkText(iban, LIMITS.iban)
  const referenceProblem = checkText(reference, LIMITS.reference)
  if (payeeProblem) problems.payee = payeeProblem
  if (ibanProblem) problems.iban = ibanProblem
  if (referenceProblem) problems.reference = referenceProblem
  const amount = normaliseAmount(inputs.amount)
  if ('problem' in amount) problems.amount = amount.problem
  if (dueDate === '') problems.due_date = 'required'
  else if (!DATE.test(dueDate)) problems.due_date = 'date_format'

  if (!customerId || Object.keys(problems).length > 0 || 'problem' in amount) {
    return { ok: false, problems, missingCustomer }
  }
  return {
    ok: true,
    request: {
      customer_id: customerId,
      language,
      barcode: null,
      payee: null,
      fields: { payee, iban, reference, amount: amount.amount, due_date: dueDate },
    },
  }
}
