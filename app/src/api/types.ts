// Types for the parts of contracts/api.md (0.2.1) the app uses so far:
// sections 1-6 (conventions, shared objects, cards, errors, personas, overview), 7 (ask) and 9 (evidence).
// The app ignores fields it does not know (contract section 1), so these types list only what it reads.

export type Language = 'en' | 'fi'

export interface Period {
  start: string
  end: string
  label: string
}

export type NumberUnit =
  | 'eur'
  | 'eur_per_day'
  | 'eur_per_week'
  | 'eur_per_month'
  | 'eur_per_year'
  | 'percent'
  | 'percentile'
  | 'count'
  | 'days'
  | 'months'

/** Contract section 2.1. The app shows `display` as is and never recomputes it. */
export interface Num {
  value: number
  unit: NumberUnit
  period: Period
  method: string
  evidence_ref: string | null
  label: string
  display: string
  id?: string
}

export interface Comparison {
  baseline: Num
  change: Num
  change_pct: Num | null
  tone: 'better' | 'worse' | 'neutral'
  label: string
}

export interface Estimate {
  label: string
  text: string
}

export type Action =
  | { type: 'open_evidence'; label: string; evidence_ref: string }
  | { type: 'ask'; label: string; prompt: string }
  | { type: 'open_whatif'; label: string; scenario: unknown }

export interface CardBase {
  card_id: string
  title: string
  subtitle: string | null
  evidence_ref: string | null
  estimate: Estimate | null
  actions: Action[]
}

export type SafeToSpendStatus = 'ok' | 'below_usual' | 'nothing_free'

export interface Component {
  key: string
  label: string
  operation: 'add' | 'subtract'
  amount: Num
}

export interface MetricCard extends CardBase {
  type: 'metric'
  status: SafeToSpendStatus | null
  primary: Num
  secondary: Num[]
  comparison: Comparison | null
  components: Component[]
}

export type BasketKey = 'regular_essentials' | 'unexpected_necessities' | 'everyday_spending'
export type BasketState = BasketKey | 'unclassified'

export interface BreakdownItem {
  key: string
  label: string
  amount: Num
  share: Num | null
  change: Num | null
  flags: ('one_off' | 'habit')[]
}

export interface BreakdownCard extends CardBase {
  type: 'breakdown'
  display_hint: 'list' | 'stacked_bar' | 'time_series'
  total: Num
  comparison: Comparison | null
  items: BreakdownItem[]
}

export interface Localised {
  en: string
  fi: string
}

export interface ReviewCard extends CardBase {
  type: 'review'
  tx_ref: string
  date: string
  category: string
  merchant: { alias: string; label: string } | null
  amount: Num
  current_basket: { key: BasketState; label: string }
  question: Localised
  options: { basket: BasketKey; label: Localised; effect: Localised }[]
  why: string
}

export interface SafeToSaveCard extends CardBase {
  type: 'safe_to_save'
  monthly: Num
  stock: Num
  stock_explanation: string
}

/** Any card; the app renders the types it knows and skips the rest. */
export type Card = MetricCard | BreakdownCard | ReviewCard | SafeToSaveCard | (CardBase & { type: string })

export interface Insight {
  insight_id: string
  kind: string
  title: string
  text: string
  text_rendered: string
  numbers: Record<string, Num>
  estimate: Estimate | null
  action: Action | null
}

export interface Persona {
  customer_id: string
  display_name: string
  age_band: string
  postal_area: { code: string; label: string }
  profile: { key: string; label: string }
  tagline: string
  default_language: Language
}

export interface PersonasResponse {
  as_of: string
  language: Language
  personas: Persona[]
}

export interface OverviewResponse {
  customer_id: string
  as_of: string
  language: Language
  greeting: string
  ai_disclosure: string
  /** The contract always has it; the core may still send null while safe to spend is being built. */
  hero: MetricCard | null
  /** May be missing from older core builds. */
  safe_to_save?: SafeToSaveCard | null
  cards: Card[]
  reviews: ReviewCard[]
  insights: Insight[]
  suggested_questions: string[]
}

export interface EvidenceRow {
  tx_id: string
  date: string
  time: string | null
  category: string
  merchant: { id: string; label: string } | null
  mcc: string | null
  /** Decimal string with the bank sign: "-24.50" is 24.50 out (contract section 9). */
  amount: string
  currency: string
}

export interface EvidenceResponse {
  evidence_ref: string
  kind: 'transactions' | 'composite' | 'peer_aggregate' | 'store_index' | string
  language: Language
  title: string
  number: Num
  method: { id: string; name: string; summary: string; doc: string | null }
  rows: EvidenceRow[]
  row_count: Num | null
  reconciles: boolean | null
  parts: { role: string; number: Num }[]
  next_cursor: string | null
  privacy_note: string
}

export interface ErrorEnvelope {
  error: { code: string; message: string; retryable: boolean }
}

// POST /api/ask (contract section 7).

export interface AskRequest {
  customer_id: string
  conversation_id: string | null
  /** At most 500 characters. */
  message: string
  language: Language | 'auto'
}

export type AskStage = 'understanding' | 'tool' | 'writing'

export interface AskMeta {
  answer_id: string
  conversation_id: string
  language: Language
  as_of: string
}

export interface AskStatus {
  /** `understanding`, `tool` or `writing`; an unknown stage is shown by its label only. */
  stage: string
  tool: string | null
  label: string
}

export type AskOutcome = 'answered' | 'clarify' | 'refused' | 'fallback'

export interface AskDone {
  answer_id: string
  outcome: AskOutcome | string
  /** The full answer with number tokens; equals the concatenated deltas. */
  text: string
  /** Tokens replaced by `display`: for screen readers and copying. */
  text_rendered: string
  cited: string[]
  follow_ups: string[]
  lesson: { key: string; title: string; text: string } | null
  refusal: { kind: string; label: string } | null
  clarify: { question: string; options: string[] } | null
  warnings: string[]
}

/** One validated event of the /api/ask stream (contract section 7.2). */
export type AskEvent =
  | { event: 'meta'; data: AskMeta }
  | { event: 'status'; data: AskStatus }
  | { event: 'card'; data: { card: Card } }
  | { event: 'numbers'; data: { numbers: Record<string, Num> } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'done'; data: AskDone }
  | { event: 'error'; data: ErrorEnvelope }
