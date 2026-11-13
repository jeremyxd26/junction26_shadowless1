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
//   evidence object built only from that overview's own data (see buildEvidence).
import type { ApiClient } from '../client.ts'
import { ApiError } from '../errors.ts'
import type {
  ErrorEnvelope,
  EvidenceResponse,
  MetricCard,
  Num,
  OverviewResponse,
  Persona,
  PersonasResponse,
  ReviewCard,
} from '../types.ts'
import contract from './contract-examples.json'

const examples = contract.examples as unknown as {
  'personas.response': PersonasResponse
  'overview.response': OverviewResponse
  'overview.response_pending': OverviewResponse
  'evidence.response': EvidenceResponse
  'evidence.response_composite': EvidenceResponse
  'error.response': ErrorEnvelope
}

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

function buildEvidence(ref: string, customerId: string): EvidenceResponse {
  if (EVIDENCE[ref]) return clone(EVIDENCE[ref])
  const overview = OVERVIEWS[customerId]
  if (overview) {
    if (overview.hero.primary.evidence_ref === ref || overview.hero.evidence_ref === ref) {
      return heroEvidence(overview.hero)
    }
    const review = overview.reviews.find((card) => card.amount.evidence_ref === ref || card.evidence_ref === ref)
    if (review) return reviewEvidence(review)
    const number = collectNumbers(overview).find((candidate) => candidate.evidence_ref === ref)
    if (number) return placeholderEvidence(number)
  }
  throw new ApiError(404, {
    code: 'evidence_not_found',
    message: 'We could not find how this number was built.',
    retryable: false,
  })
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
        const overview = OVERVIEWS[customerId]
        if (!overview) throw new ApiError(404, examples['error.response'].error)
        return clone(overview)
      }),
    evidence: (ref: string, customerId: string) => later(() => buildEvidence(ref, customerId)),
  }
}
