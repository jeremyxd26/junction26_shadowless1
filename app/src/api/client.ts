import type { EvidenceResponse, Language, OverviewResponse, PersonasResponse } from './types.ts'
import { ApiError, isErrorEnvelope } from './errors.ts'

export type ApiMode = 'mock' | 'live'

/** One interface, two implementations: `mock` (contract examples, no network) and `live` (the core). */
export interface ApiClient {
  readonly mode: ApiMode
  personas(lang: Language): Promise<PersonasResponse>
  overview(customerId: string, lang: Language): Promise<OverviewResponse>
  /** `cursor` is the previous page's `next_cursor` (contract section 9). */
  evidence(ref: string, customerId: string, lang: Language, cursor?: string): Promise<EvidenceResponse>
}

/** The core is on the same origin under /api (no CORS). VITE_API_BASE can prefix it if ever needed. */
function createLiveClient(base: string): ApiClient {
  async function get<T>(path: string, params: Record<string, string>): Promise<T> {
    const query = new URLSearchParams(params).toString()
    let response: Response
    try {
      response = await fetch(`${base}${path}?${query}`, { headers: { Accept: 'application/json' } })
    } catch {
      throw new ApiError(0, { code: 'network', message: 'No connection. Try again.', retryable: true })
    }
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      if (isErrorEnvelope(body)) throw new ApiError(response.status, body.error)
      throw new ApiError(response.status, {
        code: 'internal',
        message: 'Something went wrong. Try again.',
        retryable: response.status >= 500,
      })
    }
    // A 200 that is not a JSON object (for example a static host answering /api with
    // index.html) must not reach the screens as data.
    if (typeof body !== 'object' || body === null) {
      throw new ApiError(response.status, {
        code: 'bad_response',
        message: 'Something went wrong. Try again.',
        retryable: true,
      })
    }
    return body as T
  }

  return {
    mode: 'live',
    personas: (lang) => get<PersonasResponse>('/api/personas', { lang }),
    overview: (customerId, lang) =>
      get<OverviewResponse>(`/api/overview/${encodeURIComponent(customerId)}`, { lang }),
    evidence: (ref, customerId, lang, cursor) =>
      get<EvidenceResponse>(`/api/evidence/${encodeURIComponent(ref)}`, {
        customer_id: customerId,
        lang,
        ...(cursor ? { cursor } : {}),
      }),
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
  }
}

/** Selected once at build time by VITE_API_MODE; anything but `live` means mock. */
export const api: ApiClient =
  import.meta.env.VITE_API_MODE === 'live'
    ? createLiveClient(import.meta.env.VITE_API_BASE ?? '')
    : createLazyMockClient()
