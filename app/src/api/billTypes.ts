// Types for contract section 11: POST /api/bill/explain (11.1-11.3) and the sample-bill reading
// (11.4: GET /api/bill/samples, POST /api/bill/read). Section 11.4 is marked "not implemented yet"
// in the contract, so its types may change until #249 and #250 are on the dev environment.
// Kept apart from types.ts so the bill flow can grow without touching the shared types.
import type { Comparison, Language, Num } from './types.ts'

// ---- 11.1 Request -------------------------------------------------------------------------

/** The bill's details as the user typed or confirmed them. Every value is a string as typed. */
export interface BillFields {
  /** 1 to 70 characters. */
  payee: string
  /** At most 42 characters; spaces are ignored by the service. */
  iban: string
  /** National or `RF`, at most 35 characters; spaces are ignored by the service. */
  reference: string
  /** Decimal string in euros with a dot and at most two decimals, for example "145.00". */
  amount: string
  /** Exactly `YYYY-MM-DD`. */
  due_date: string
}

/** Exactly one of `barcode` and `fields` is set; `payee` only beside `barcode`. */
export interface BillExplainRequest {
  customer_id: string
  language: Language
  /** 54 digits, at most 80 characters with spaces. */
  barcode: string | null
  payee: string | null
  fields: BillFields | null
}

/** Stable codes of a 422 `invalid_bill` (section 11.1). An unknown code is shown by its message. */
export type BillErrorReason =
  | 'one_of_barcode_or_fields'
  | 'payee_with_fields'
  | 'barcode_length'
  | 'barcode_version'
  | 'barcode_chars'
  | 'barcode_check'
  | 'due_date'
  | 'amount_missing'
  | 'due_date_missing'
  | 'amount_too_large'

/** The error envelope of section 4 plus `reason` on a 422 `invalid_bill`. */
export interface BillErrorEnvelope {
  error: { code: string; message: string; retryable: boolean; reason?: BillErrorReason | string }
}

// ---- 11.2 Response ------------------------------------------------------------------------

export interface BillRead {
  source: 'barcode' | 'fields'
  /** As sent, or null for a barcode sent without a name. */
  payee: string | null
  /** Formatted for display (groups of four). */
  iban: string
  /** Formatted for display. */
  reference: string
  /** `bill_barcode@1` or `user_input@1`; `evidence_ref` is null; the period is the due date. */
  amount: Num
  due_date: string
}

export interface BillChecks {
  iban: 'pass' | 'fail'
  reference: 'pass' | 'fail'
  due_date: 'pass' | 'past'
}

export interface BillMatch {
  status: 'matched' | 'not_matched' | 'no_payee'
  bill_id: string | null
  label: string | null
  text: string
}

export interface BillBasket {
  key: 'regular_essentials' | 'unexpected_necessities' | string
  label: string
  text: string
}

export interface BillSafeToSpend {
  effect: 'after_payday' | 'excess_only' | 'full'
  next_payday: string
  reserved: Num | null
  counted: Num | null
  free_until_payday_before: Num
  free_until_payday_after: Num | null
  before: Num
  /** Null for `after_payday`; can equal `before` when the monthly budget limits it. */
  after: Num | null
  text: string
}

/**
 * The forecast balance on the bill's due date (since contract 0.3.4, #421). Every Number is
 * `null` for `outside_forecast`; `shortfall` only for `not_covered`; `chip` (an `ask` action) only
 * for `not_covered`. The status never removes the payment draft.
 */
export interface BillForecast {
  status: 'covered' | 'tight' | 'not_covered' | 'outside_forecast' | string
  before: Num | null
  already_counted: Num | null
  counted: Num | null
  after: Num | null
  shortfall: Num | null
  /** One sentence that embeds the displays it cites; shown as plain text. */
  text: string
  chip: { type: 'ask'; label: string; prompt: string } | null
}

export interface BillGlossaryEntry {
  term: 'reference_number' | 'due_date' | 'virtual_barcode' | 'late_payment_interest' | string
  label: string
  text: string
}

/** What the host gets in `sentti.paymentDraft` (section 11.3), exactly as the action carries it. */
export interface PaymentDraft {
  payee: string | null
  /** Normalised, no spaces. */
  iban: string
  /** Normalised, no spaces. */
  reference: string
  amount: Num
  due_date: string
}

export interface AddToPaymentsAction {
  type: 'add_to_payments'
  label: string
  draft: PaymentDraft
}

export interface BillSignal {
  code: 'iban_check_failed' | 'reference_check_failed' | 'new_payee' | 'amount_above_usual' | 'short_term' | string
  /** One plain sentence (two for a failed check); never a verdict. */
  text: string
  /** The numbers whose `display` the sentence cites, in order. */
  numbers: Num[]
}

export interface BillExplainResponse {
  customer_id: string
  as_of: string
  language: Language
  bill: BillRead
  checks: BillChecks
  match: BillMatch
  comparison: Comparison | null
  basket: BillBasket
  safe_to_spend: BillSafeToSpend | null
  /** Since 0.3.4; missing or `null` from an older API, or when the forecast cannot be computed. */
  forecast?: BillForecast | null
  glossary: BillGlossaryEntry[]
  /** At most one; empty when a check failed. The app shows the button only when it is here. */
  actions: AddToPaymentsAction[]
  warnings: string[]
  signals: BillSignal[]
}

// ---- 11.4 Sample bills (not implemented yet in the core) ----------------------------------

export interface BillSample {
  sample_id: string
  title: string
  /** The bill's own language, not the request's. */
  language: Language
  image_url: string
}

export interface BillSamplesResponse {
  samples: BillSample[]
}

export interface BillReadRequest {
  customer_id: string
  language: Language
  sample_id: string
}

/** One field as the reader proposes it; a reading carries no Number objects. */
export interface BillReadField {
  /** Normalised string, for example "FI2112345600000785" or "812.40". */
  value: string
  /** The same, formatted for display. */
  display: string
  /** `checked` only when code checked it (a parsed barcode, or a passing check digit). */
  status: 'checked' | 'unchecked'
  source: 'barcode' | 'printed'
  note: string | null
}

export type BillReadFieldKey = 'payee' | 'iban' | 'reference' | 'amount' | 'due_date' | 'barcode'

export interface BillReadResponse {
  sample_id: string
  /** The request's language. */
  language: Language
  /** `null` when a field was not found or failed its format check (dropped, never repaired). */
  fields: Record<BillReadFieldKey, BillReadField | null>
  /** Always true: the user confirms every field before it reaches an explanation. */
  needs_confirmation: true
}
