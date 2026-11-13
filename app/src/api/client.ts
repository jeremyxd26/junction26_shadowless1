import type { AskRequest, EvidenceResponse, Language, OverviewResponse, PersonasResponse } from './types.ts'
import { ApiError, isErrorEnvelope } from './errors.ts'

export type ApiMode = 'mock' | 'live'

/** One interface, two implementations: `mock` (contract examples, no network) and `live` (the core). */
export interface ApiClient {
  readonly mode: ApiMode
  personas(lang: Language): Promise<PersonasResponse>
  overview(customerId: string, lang: Language): Promise<OverviewResponse>
  /** `cursor` is the previous page's `next_cursor` (contract section 9). */
  evidence(ref: string, customerId: string, lang: Language, cursor?: string): Promise<EvidenceResponse>
  /**
   * POST /api/ask as a text/event-stream (contract section 7). Errors before the stream reject
   * with an ApiError; the open stream is read with `readAskStream`. `signal` stops the answer.
   */
  ask(request: AskRequest, signal?: AbortSignal): Promise<ReadableStream<Uint8Array>>
}

const NETWORK_ERROR = { code: 'network', message: 'No connection. Try again.', retryable: true }

/** An HTTP error in the contract's envelope, or a generic one when the body is not an envelope. */
function httpError(status: number, body: unknown): ApiError {
  if (isErrorEnvelope(body)) return new ApiError(status, body.error)
  return new ApiError(status, {
    code: 'internal',
    message: 'Something went wrong. Try again.',
    retryable: status >= 500,
  })
}

/** The core is on the same origin under /api (no CORS). VITE_API_BASE can prefix it if ever needed. */
function createLiveClient(base: string): ApiClient {
  async function get<T>(path: string, params: Record<string, string>): Promise<T> {
    const query = new URLSearchParams(params).toString()
    let response: Response
    try {
      response = await fetch(`${base}${path}?${query}`, { headers: { Accept: 'application/json' } })
    } catch {
      throw new ApiError(0, NETWORK_ERROR)
    }
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) throw httpError(response.status, body)
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

  async function ask(request: AskRequest, signal?: AbortSignal): Promise<ReadableStream<Uint8Array>> {
    let response: Response
    try {
      response = await fetch(`${base}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(request),
        signal,
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw new ApiError(0, NETWORK_ERROR)
    }
    // Validation errors come before the stream, as plain JSON with the envelope (section 7.1).
    if (!response.ok) throw httpError(response.status, await response.json().catch(() => null))
    const type = response.headers.get('Content-Type') ?? ''
    if (!type.startsWith('text/event-stream') || !response.body) {
      await response.body?.cancel().catch(() => undefined)
      throw new ApiError(response.status, {
        code: 'bad_response',
        message: 'Something went wrong. Try again.',
        retryable: true,
      })
    }
    return response.body
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
    ask,
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
    ask: (request, signal) => client.then((mock) => mock.ask(request, signal)),
  }
}

/** Selected once at build time by VITE_API_MODE; anything but `live` means mock. */
export const api: ApiClient =
  import.meta.env.VITE_API_MODE === 'live'
    ? createLiveClient(import.meta.env.VITE_API_BASE ?? '')
    : createLazyMockClient()
