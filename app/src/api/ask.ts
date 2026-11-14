// POST /api/ask as a text/event-stream (contract section 7). Errors before the stream reject
// with an ApiError; the open stream is read with `readAskStream`. `signal` stops the answer.
// Like the API client, the mode is picked once at build time by VITE_API_MODE, and the mock is
// loaded on first use, so a live build does not ship the example data.
import { strings } from '../lib/i18n.ts'
import { ApiError, isErrorEnvelope } from './errors.ts'
import type { AskRequest } from './types.ts'

export type Ask = (request: AskRequest, signal?: AbortSignal) => Promise<ReadableStream<Uint8Array>>

/** The core is on the same origin under /api (no CORS). VITE_API_BASE can prefix it if ever needed. */
function liveAsk(base: string): Ask {
  return async (request, signal) => {
    // Errors the app makes itself use the app's own texts; errors from the core come localised.
    const t = strings(request.language === 'fi' ? 'fi' : 'en')
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
      throw new ApiError(0, { code: 'network', message: t.errorOffline, retryable: true })
    }
    // Validation errors come before the stream, as plain JSON with the envelope (section 7.1).
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null)
      if (isErrorEnvelope(body)) throw new ApiError(response.status, body.error)
      throw new ApiError(response.status, {
        code: 'internal',
        message: t.errorRetry,
        retryable: response.status >= 500,
      })
    }
    // A 200 that is not an event stream (for example a static host answering /api with
    // index.html) must not reach the screen as an answer.
    const type = response.headers.get('Content-Type') ?? ''
    if (!type.startsWith('text/event-stream') || !response.body) {
      await response.body?.cancel().catch(() => undefined)
      throw new ApiError(response.status, {
        code: 'bad_response',
        message: t.errorRetry,
        retryable: true,
      })
    }
    return response.body
  }
}

const lazyMockAsk: Ask = (request, signal) => import('./mock/mockAsk.ts').then((module) => module.mockAsk(request, signal))

export const ask: Ask =
  import.meta.env.VITE_API_MODE === 'live' ? liveAsk(import.meta.env.VITE_API_BASE ?? '') : lazyMockAsk
