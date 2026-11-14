// The bill flow's API calls (contract section 11). One switch, BILL_LIVE, picks the core or the
// mock for all three calls. It is off unless the build is live AND VITE_BILL_LIVE=true, because
// the endpoints are not on the dev environment yet (#242 explain, #249 samples, #250 read).
// Bill fields are never put into a URL, a history entry or the console: they travel only in a
// POST body.
import type {
  BillErrorEnvelope,
  BillExplainRequest,
  BillExplainResponse,
  BillReadRequest,
  BillReadResponse,
  BillSamplesResponse,
} from './billTypes.ts'
import { ApiError, isErrorEnvelope } from './errors.ts'
import type { Language } from './types.ts'
import { strings } from '../lib/i18n.ts'

export const BILL_LIVE = import.meta.env.VITE_API_MODE === 'live' && import.meta.env.VITE_BILL_LIVE === 'true'

/** An API error that keeps the `reason` of a 422 `invalid_bill` (section 11.1). */
export class BillApiError extends ApiError {
  readonly reason: string | null

  constructor(status: number, envelope: BillErrorEnvelope['error']) {
    super(status, envelope)
    this.name = 'BillApiError'
    this.reason = typeof envelope.reason === 'string' ? envelope.reason : null
  }
}

export interface BillApi {
  samples(lang: Language): Promise<BillSamplesResponse>
  read(request: BillReadRequest): Promise<BillReadResponse>
  explain(request: BillExplainRequest): Promise<BillExplainResponse>
}

type Body = Record<string, unknown>

function isRecord(value: unknown): value is Body {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const isSamples = (body: Body) => Array.isArray(body.samples)
const isReading = (body: Body) => typeof body.sample_id === 'string' && isRecord(body.fields)
const isExplanation = (body: Body) =>
  isRecord(body.bill) &&
  isRecord(body.checks) &&
  isRecord(body.match) &&
  isRecord(body.basket) &&
  (body.safe_to_spend === null || isRecord(body.safe_to_spend)) &&
  ['glossary', 'actions', 'warnings', 'signals'].every((key) => Array.isArray(body[key]))

function createLiveBillApi(base: string): BillApi {
  /**
   * `?lang=` too, so a body the core cannot validate (400) is answered in the user's language;
   * a body that validates is answered in its `language` (contract sections 1 and 11.1).
   */
  async function call<T>(
    path: string,
    lang: Language,
    init: RequestInit,
    isShape: (body: Body) => boolean,
  ): Promise<T> {
    const t = strings(lang)
    let response: Response
    try {
      response = await fetch(`${base}${path}?${new URLSearchParams({ lang })}`, {
        ...init,
        headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
      })
    } catch {
      throw new BillApiError(0, { code: 'network', message: t.errorOffline, retryable: true })
    }
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      if (isErrorEnvelope(body)) throw new BillApiError(response.status, (body as BillErrorEnvelope).error)
      throw new BillApiError(response.status, { code: 'internal', message: t.errorRetry, retryable: response.status >= 500 })
    }
    if (!isRecord(body) || !isShape(body)) {
      throw new BillApiError(response.status, { code: 'bad_response', message: t.errorRetry, retryable: true })
    }
    return body as T
  }

  const post = (payload: { language: Language }) => ({ method: 'POST', body: JSON.stringify(payload) })

  return {
    samples: (lang) => call<BillSamplesResponse>('/api/bill/samples', lang, {}, isSamples),
    read: (request) => call<BillReadResponse>('/api/bill/read', request.language, post(request), isReading),
    explain: (request) => call<BillExplainResponse>('/api/bill/explain', request.language, post(request), isExplanation),
  }
}

/** The mock is loaded on first use, so it stays out of the main bundle. */
function createLazyMockBillApi(): BillApi {
  const mock = import('./mock/bill.ts').then((module) => module.createMockBillApi())
  return {
    samples: (lang) => mock.then((api) => api.samples(lang)),
    read: (request) => mock.then((api) => api.read(request)),
    explain: (request) => mock.then((api) => api.explain(request)),
  }
}

export const billApi: BillApi = BILL_LIVE
  ? createLiveBillApi(import.meta.env.VITE_API_BASE ?? '')
  : createLazyMockBillApi()
