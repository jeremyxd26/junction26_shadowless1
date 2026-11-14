// Mock implementation of the API client. It runs in the page (no service worker, so it also
// works inside iOS WKWebView) and serves the contract's own examples, copied unchanged into
// contract-examples.json by scripts/extract-contract-examples.mjs.
//
// Where the contract has no example, the mock says so instead of inventing data:
// - Personas: the contract's list, plus Sanna (CUST00860, the demo start) from core/config/personas.yaml,
//   because the contract's pending-review overview is hers.
// - Overview: CUST00042 (Aino) and CUST00860 (Sanna) have examples; other customers get the
//   contract's customer_not_found error.
// - Evidence: the two contract examples by ref. Other refs that appear in a mock overview get an
//   evidence object built only from that overview's own data (see buildEvidence). The examples
//   hold only a first page of rows, so a request with a cursor gets an empty last page.
// - Labels (POST /api/baskets/label): the contract's label examples. The mock remembers the answer
//   for this page load, and the next overview carries the example's `after` numbers, no review and
//   no waiting row. Undoing "I chose it" has no example: it is the "I chose it" example run backwards.
//   The basket shares of that overview are the basket amounts over the total, as the core counts
//   them (metrics.md, baskets.share_pct); the contract has no post-answer overview example.
import type { ApiClient } from '../client.ts'
import { ApiError } from '../errors.ts'
import { applyChanges, isBasketsCard } from '../../lib/changes.ts'
import type {
  BasketKey,
  ErrorEnvelope,
  Language,
  EvidenceResponse,
  LabelChange,
  LabelRequest,
  LabelResponse,
  MetricCard,
  Num,
  OverviewResponse,
  Persona,
  PersonasResponse,
  ReviewCard,
  SafeToSaveCard,
  WhatIfResponse,
  WhatIfScenarioRequest,
} from '../types.ts'
import contract from './contract-examples.json'

const examples = contract.examples as unknown as {
  'personas.response': PersonasResponse
  'overview.response': OverviewResponse
  'overview.response_pending': OverviewResponse
  'overview.response_no_hero': OverviewResponse
  'evidence.response': EvidenceResponse
  'evidence.response_composite': EvidenceResponse
  'error.response': ErrorEnvelope
  'label.response': LabelResponse
  'label.response_wanted': LabelResponse
  'label.response_undo': LabelResponse
  'label.error': ErrorEnvelope
  'card.safe_to_save': SafeToSaveCard
  'card.safe_to_save_aleksi': SafeToSaveCard
  'card.safe_to_save_zero': SafeToSaveCard
  'card.safe_to_save_everyday': SafeToSaveCard
  'whatif.response': WhatIfResponse
}

/** Card examples shown on the mock-only `/cards` page; their chips open placeholder evidence. */
const CARD_EXAMPLES = [
  examples['card.safe_to_save'],
  examples['card.safe_to_save_aleksi'],
  examples['card.safe_to_save_zero'],
  examples['card.safe_to_save_everyday'],
]

/** Sanna as in core/config/personas.yaml (lead persona of the demo). */
const SANNA: Persona = {
  customer_id: 'CUST00860',
  display_name: 'Sanna',
  age_band: '35-44',
  postal_area: { code: '00590', label: 'Helsinki 00590' },
  profile: { key: 'big_ticket', label: 'Big ticket' },
  tagline: 'A large home and tech purchase in late September, on top of regular bills.',
  default_language: 'en',
}

const OVERVIEWS: Record<string, OverviewResponse> = {
  CUST00042: examples['overview.response'],
  CUST00860: examples['overview.response_pending'],
}

const EVIDENCE: Record<string, EvidenceResponse> = {
  [examples['evidence.response'].evidence_ref]: examples['evidence.response'],
  [examples['evidence.response_composite'].evidence_ref]: examples['evidence.response_composite'],
}

const PRIVACY_NOTE = 'Only you can see this. Transactions are never sent to the AI model.'

/** A short wait so loading states are visible in mock mode too. */
function later<T>(make: () => T, ms = 180): Promise<T> {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        resolve(make())
      } catch (error) {
        reject(error)
      }
    }, ms)
  })
}

function clone<T>(value: T): T {
  return structuredClone(value)
}

/** Every Number object in a response, found by walking it. */
function collectNumbers(value: unknown, into: Num[] = []): Num[] {
  if (Array.isArray(value)) {
    for (const item of value) collectNumbers(item, into)
  } else if (typeof value === 'object' && value !== null) {
    const record = value as Record<string, unknown>
    if (typeof record.display === 'string' && typeof record.method === 'string' && 'value' in record) {
      into.push(record as unknown as Num)
    }
    for (const child of Object.values(record)) collectNumbers(child, into)
  }
  return into
}

function heroEvidence(hero: MetricCard): EvidenceResponse {
  return {
    evidence_ref: hero.primary.evidence_ref ?? '',
    kind: 'composite',
    language: 'en',
    title: hero.title,
    number: hero.primary,
    method: {
      id: hero.primary.method,
      name: hero.primary.label,
      summary: hero.estimate?.text ?? '',
      doc: 'docs/design/metrics.md',
    },
    rows: [],
    row_count: null,
    reconciles: null,
    parts: hero.components.map((component) => ({ role: component.key, number: component.amount })),
    next_cursor: null,
    privacy_note: PRIVACY_NOTE,
  }
}

function reviewEvidence(review: ReviewCard): EvidenceResponse {
  return {
    evidence_ref: review.amount.evidence_ref ?? '',
    kind: 'transactions',
    language: 'en',
    title: review.subtitle ?? review.title,
    number: review.amount,
    method: {
      id: review.amount.method,
      name: 'Total spending',
      summary: 'The purchase this question is about, as it appears on your account.',
      doc: 'docs/design/agent-core.md#62-data-tools',
    },
    rows: [
      {
        tx_id: 'tx_mock_review',
        date: review.date,
        time: null,
        category: review.category,
        merchant: review.merchant ? { id: review.merchant.alias, label: review.merchant.label } : null,
        mcc: null,
        amount: (-review.amount.value).toFixed(2),
        currency: 'EUR',
        // Money out: the purchase's own display with the bank sign, as the core writes rows.
        display: `-${review.amount.display}`,
      },
    ],
    row_count: null,
    reconciles: true,
    parts: [],
    next_cursor: null,
    privacy_note: PRIVACY_NOTE,
  }
}

/** A number with no evidence example in the contract: show the number and its method, no rows. */
function placeholderEvidence(number: Num): EvidenceResponse {
  return {
    evidence_ref: number.evidence_ref ?? '',
    kind: 'composite',
    language: 'en',
    title: number.label,
    number,
    method: {
      id: number.method,
      name: number.label,
      summary: 'Mock mode: the contract has no evidence example for this number yet, so no transactions are shown.',
      doc: null,
    },
    rows: [],
    row_count: null,
    reconciles: null,
    parts: [],
    next_cursor: null,
    privacy_note: PRIVACY_NOTE,
  }
}

/** The answer the customer gave in this page load, by customer. */
const answers: Record<string, BasketKey> = {}

/** The contract example for an answer. */
function answerExample(basket: BasketKey): LabelResponse {
  return clone(basket === 'everyday_spending' ? examples['label.response_wanted'] : examples['label.response'])
}

function reversed(changes: LabelChange[]): LabelChange[] {
  return changes.map((change) => ({ ...change, before: change.after, after: change.before }))
}

/** Two moves in a row as one: the first `before`, the last `after`; numbers that end where they began drop out. */
function chained(first: LabelChange[], second: LabelChange[]): LabelChange[] {
  const merged = new Map<string, LabelChange>()
  for (const change of [...first, ...second]) {
    const earlier = merged.get(change.key)
    merged.set(change.key, earlier ? { ...change, before: earlier.before } : change)
  }
  return [...merged.values()].filter((change) => change.before.value !== change.after.value)
}

/** Shares as the core counts them: each basket amount over the total, in percent, one decimal. */
function withShares(overview: OverviewResponse): OverviewResponse {
  return {
    ...overview,
    cards: overview.cards.map((card) => {
      if (!isBasketsCard(card) || card.total.value <= 0) return card
      const items = card.items.map((item) => {
        if (!item.share) return item
        const value = Math.round((item.amount.value / card.total.value) * 1000) / 10
        return { ...item, share: { ...item.share, value, display: `${value.toFixed(1)}%` } }
      })
      return { ...card, items }
    }),
  }
}

/**
 * `?mock=no_hero` in the page URL serves the contract's `overview.response_no_hero` for its
 * customer (safe to spend cannot be computed, contract 0.2.2), to check that fallback.
 */
function noHero(customerId: string): OverviewResponse | undefined {
  const example = examples['overview.response_no_hero']
  const asked = new URLSearchParams(window.location.search).get('mock') === 'no_hero'
  return asked && example.customer_id === customerId ? example : undefined
}

/** The overview as the core would serve it now: pending, or with the answer applied. */
function currentOverview(customerId: string): OverviewResponse | undefined {
  const base = noHero(customerId) ?? OVERVIEWS[customerId]
  const basket = answers[customerId]
  if (!base || !basket) return base
  const answered = applyChanges(clone(base), answerExample(basket).changes)
  return withShares({
    ...answered,
    reviews: [],
    cards: answered.cards.map((card) =>
      isBasketsCard(card) ? { ...card, items: card.items.filter((item) => item.key !== 'unclassified') } : card,
    ),
  })
}

const TX_REF_NOT_FOUND = {
  code: 'tx_ref_not_found',
  message: 'This question is no longer open.',
  retryable: false,
}

function label(request: LabelRequest): LabelResponse {
  const base = OVERVIEWS[request.customer_id]
  if (!base) throw new ApiError(404, examples['error.response'].error)
  const review = base.reviews[0]
  if (!review || review.tx_ref !== request.tx_ref) throw new ApiError(404, TX_REF_NOT_FOUND)
  if (request.basket !== null && !review.options.some((option) => option.basket === request.basket)) {
    throw new ApiError(422, examples['label.error'].error)
  }

  const current = answers[request.customer_id] ?? null
  if (request.basket === current) {
    // Idempotent: the same answer again changes nothing.
    const same = current ? answerExample(current) : clone(examples['label.response_undo'])
    return { ...same, changed: false, changes: [] }
  }
  if (request.basket === null && current) {
    delete answers[request.customer_id]
    return { ...clone(examples['label.response_undo']), changes: reversed(answerExample(current).changes) }
  }
  const basket = request.basket as BasketKey
  answers[request.customer_id] = basket
  const response = answerExample(basket)
  if (current) response.changes = chained(reversed(answerExample(current).changes), response.changes)
  return response
}

function buildEvidence(ref: string, customerId: string): EvidenceResponse {
  if (EVIDENCE[ref]) return clone(EVIDENCE[ref])
  // The overview as served now first, then the pending one: refs from before an answer stay valid.
  const overviews = [currentOverview(customerId), OVERVIEWS[customerId]]
  for (const overview of overviews) {
    if (!overview) continue
    if (overview.hero && (overview.hero.primary.evidence_ref === ref || overview.hero.evidence_ref === ref)) {
      return heroEvidence(overview.hero)
    }
    const review = overview.reviews.find((card) => card.amount.evidence_ref === ref || card.evidence_ref === ref)
    if (review) return reviewEvidence(review)
    const number = collectNumbers(overview).find((candidate) => candidate.evidence_ref === ref)
    if (number) return placeholderEvidence(number)
  }
  const cardNumber = collectNumbers(CARD_EXAMPLES).find((candidate) => candidate.evidence_ref === ref)
  if (cardNumber) return placeholderEvidence(cardNumber)
  throw new ApiError(404, {
    code: 'evidence_not_found',
    message: 'We could not find how this number was built.',
    retryable: false,
  })
}

const round2 = (value: number) => Math.round(value * 100) / 100

const RATE_SUFFIX: Partial<Record<Num['unit'], { en: string; fi: string }>> = {
  eur: { en: '', fi: '' },
  eur_per_week: { en: ' a week', fi: ' / vk' },
  eur_per_month: { en: ' a month', fi: ' / kk' },
  eur_per_year: { en: ' a year', fi: ' / v' },
}

/** Money the way the core's formatter writes it (contract 0.2.2, section 2.1): €1,234.56 a month / 1 234,56 € / kk. */
function money(value: number, unit: Num['unit'], lang: Language): string {
  const [whole, frac] = Math.abs(value).toFixed(2).split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, lang === 'fi' ? ' ' : ',')
  const sign = value < 0 && round2(value) !== 0 ? '-' : ''
  const suffix = RATE_SUFFIX[unit]?.[lang] ?? ''
  return lang === 'fi' ? `${sign}${grouped},${frac} €${suffix}` : `${sign}€${grouped}.${frac}${suffix}`
}

function withDisplay(number: Num, value: number, lang: Language): Num {
  return { ...number, value, display: money(value, number.unit, lang) }
}

/** The contract's `whatif.error` (0.2.2), in the request's language like the core. */
const WHATIF_ERROR = {
  en: 'This scenario cannot be calculated.',
  fi: 'Tätä tilannetta ei voi laskea.',
}

/**
 * What-if in mock mode: the contract has one response example (Restaurants, 20%). The mock scales
 * it for other cuts of the same selection by the contract's own rule (section 8, metrics.md
 * section 4): the saving is `cut_pct` of the example's baseline, per week × 7 / 30.4375 days, per
 * year × 12. At 20% this gives the example's numbers exactly. Amounts are written in the request
 * language like the core does; the example's texts stay English. Any other selection gets 422.
 */
function mockWhatIf(scenario: WhatIfScenarioRequest, lang: Language): WhatIfResponse {
  const example = examples['whatif.response']
  const { selection, cut_pct: cut } = scenario
  const same =
    selection.kind === example.scenario.selection.kind &&
    selection.value.toLowerCase() === example.scenario.selection.value.toLowerCase()
  if (!same || !Number.isInteger(cut) || cut < 1 || cut > 100) {
    throw new ApiError(422, { code: 'invalid_scenario', message: WHATIF_ERROR[lang], retryable: false })
  }
  const month = round2((example.baseline_per_month.value * cut) / 100)
  const week = round2((month * 7) / 30.4375)
  const year = round2(month * 12)
  const response = clone(example)
  const assumption = `Average of your last 6 full months (one-off purchases left out), cut by ${cut}%.`
  response.language = lang
  response.scenario.cut_pct = { ...response.scenario.cut_pct, value: cut, display: lang === 'fi' ? `${cut} %` : `${cut}%` }
  response.scenario.label = `Spend ${cut}% less on restaurants`
  response.saving_per_month = withDisplay(response.saving_per_month, month, lang)
  response.saving_per_week = withDisplay(response.saving_per_week, week, lang)
  response.saving_per_year = withDisplay(response.saving_per_year, year, lang)
  response.baseline_per_month = withDisplay(response.baseline_per_month, response.baseline_per_month.value, lang)
  response.one_off_excluded = withDisplay(response.one_off_excluded, response.one_off_excluded.value, lang)
  response.regular_excluded = withDisplay(response.regular_excluded, response.regular_excluded.value, lang)
  response.assumptions = [assumption, ...response.assumptions.slice(1)]
  response.estimate = response.estimate && { ...response.estimate, text: assumption }
  return response
}

export function createMockClient(): ApiClient {
  return {
    mode: 'mock',
    personas: () =>
      later(() => {
        const response = clone(examples['personas.response'])
        response.personas = [SANNA, ...response.personas]
        return response
      }),
    overview: (customerId: string) =>
      later(() => {
        const overview = currentOverview(customerId)
        if (!overview) throw new ApiError(404, examples['error.response'].error)
        return clone(overview)
      }),
    evidence: (ref: string, customerId: string, _lang, cursor?: string) =>
      later(() => {
        const evidence = buildEvidence(ref, customerId)
        // The contract shows only the first page of rows; any next page is empty and the last.
        return cursor ? { ...evidence, rows: [], next_cursor: null } : evidence
      }),
    label: (request: LabelRequest) => later(() => label(request)),
    // About the dev host's speed (0.5 s), so the sheet's loading state shows in mock mode too.
    whatIf: (_customerId: string, scenario: WhatIfScenarioRequest, lang: Language) =>
      later(() => mockWhatIf(scenario, lang), 500),
  }
}
