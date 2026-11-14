import type {
  EvidenceResponse,
  Language,
  OverviewResponse,
  PersonasResponse,
  WhatIfResponse,
  WhatIfScenarioRequest,
} from './types.ts'
import { ApiError, isErrorEnvelope } from './errors.ts'
import { strings } from '../lib/i18n.ts'

export type ApiMode = 'mock' | 'live'

/** One interface, two implementations: `mock` (contract examples, no network) and `live` (the core). */
export interface ApiClient {
  readonly mode: ApiMode
  personas(lang: Language): Promise<PersonasResponse>
  overview(customerId: string, lang: Language): Promise<OverviewResponse>
  /** `cursor` is the previous page's `next_cursor` (contract section 9). */
  evidence(ref: string, customerId: string, lang: Language, cursor?: string): Promise<EvidenceResponse>
  /** Contract section 8: the deterministic what-if calculator. Errors come in `lang`. */
  whatIf(customerId: string, scenario: WhatIfScenarioRequest, lang: Language): Promise<WhatIfResponse>
}

type Body = Record<string, unknown>

function isRecord(value: unknown): value is Body {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasArrays(body: Body, ...keys: string[]): boolean {
  return keys.every((key) => Array.isArray(body[key]))
}

// The fields each screen reads without further checks. A body that lacks them is answered like
// any other bad response (an error with "Try again"), not left to the error boundary.
const isPersonas = (body: Body) => hasArrays(body, 'personas')
const isOverview = (body: Body) =>
  typeof body.greeting === 'string' &&
  (body.hero == null || isRecord(body.hero)) &&
  (body.safe_to_save == null || isRecord(body.safe_to_save)) &&
  hasArrays(body, 'cards', 'reviews', 'insights', 'suggested_questions')
const isEvidence = (body: Body) => isRecord(body.number) && isRecord(body.method) && hasArrays(body, 'rows', 'parts')
const isWhatIf = (body: Body) =>
  isRecord(body.scenario) &&
  isRecord(body.saving_per_month) &&
  isRecord(body.saving_per_week) &&
  isRecord(body.saving_per_year) &&
  isRecord(body.baseline_per_month) &&
  isRecord(body.one_off_excluded) &&
  isRecord(body.regular_excluded) &&
  hasArrays(body, 'assumptions', 'caveats')

/** The core is on the same origin under /api (no CORS). VITE_API_BASE can prefix it if ever needed. */
function createLiveClient(base: string): ApiClient {
  async function get<T>(path: string, params: Record<string, string>, lang: Language, isShape: (body: Body) => boolean): Promise<T> {
    // Errors the app makes itself use the app's own texts; errors from the core come localised.
    const t = strings(lang)
    const query = new URLSearchParams({ ...params, lang }).toString()
    let response: Response
    try {
      response = await fetch(`${base}${path}?${query}`, { headers: { Accept: 'application/json' } })
    } catch {
      throw new ApiError(0, { code: 'network', message: t.errorOffline, retryable: true })
    }
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      if (isErrorEnvelope(body)) throw new ApiError(response.status, body.error)
      throw new ApiError(response.status, {
        code: 'internal',
        message: t.errorRetry,
        retryable: response.status >= 500,
      })
    }
    // A 200 that is not the expected JSON object (for example a static host answering /api with
    // index.html, an array, or an object without the fields the screen reads) must not reach the
    // screens as data.
    if (!isRecord(body) || !isShape(body)) {
      throw new ApiError(response.status, { code: 'bad_response', message: t.errorRetry, retryable: true })
    }
    return body as T
  }

  /** POST with a JSON body; the core answers errors in the body's `language`. */
  async function post<T>(path: string, payload: unknown, lang: Language, isShape: (body: Body) => boolean): Promise<T> {
    const t = strings(lang)
    let response: Response
    try {
      response = await fetch(`${base}${path}`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    } catch {
      throw new ApiError(0, { code: 'network', message: t.errorOffline, retryable: true })
    }
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      if (isErrorEnvelope(body)) throw new ApiError(response.status, body.error)
      throw new ApiError(response.status, {
        code: 'internal',
        message: t.errorRetry,
        retryable: response.status >= 500,
      })
    }
    if (!isRecord(body) || !isShape(body)) {
      throw new ApiError(response.status, { code: 'bad_response', message: t.errorRetry, retryable: true })
    }
    return body as T
  }

  return {
    mode: 'live',
    personas: (lang) => get<PersonasResponse>('/api/personas', {}, lang, isPersonas),
    overview: (customerId, lang) =>
      get<OverviewResponse>(`/api/overview/${encodeURIComponent(customerId)}`, {}, lang, isOverview),
    evidence: (ref, customerId, lang, cursor) =>
      get<EvidenceResponse>(
        `/api/evidence/${encodeURIComponent(ref)}`,
        { customer_id: customerId, ...(cursor ? { cursor } : {}) },
        lang,
        isEvidence,
      ),
    whatIf: (customerId, scenario, lang) =>
      post<WhatIfResponse>('/api/whatif', { customer_id: customerId, scenario, language: lang }, lang, isWhatIf),
  }
}

/** The mock is loaded on first use, so a live build does not ship the example data. */
function createLazyMockClient(): ApiClient {
  const client = import('./mock/mockClient.ts').then((module) => module.createMockClient())
  return {
    mode: 'mock',
    personas: (lang) => client.then((mock) => mock.personas(lang)),
    overview: (customerId, lang) => client.then((mock) => mock.overview(customerId, lang)),
    evidence: (ref, customerId, lang, cursor) => client.then((mock) => mock.evidence(ref, customerId, lang, cursor)),
    whatIf: (customerId, scenario, lang) => client.then((mock) => mock.whatIf(customerId, scenario, lang)),
  }
}

/** Selected once at build time by VITE_API_MODE; anything but `live` means mock. */
export const api: ApiClient =
  import.meta.env.VITE_API_MODE === 'live'
    ? createLiveClient(import.meta.env.VITE_API_BASE ?? '')
    : createLazyMockClient()
