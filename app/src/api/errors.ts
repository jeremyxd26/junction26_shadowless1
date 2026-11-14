import type { ErrorEnvelope } from './types.ts'

/** An error in the contract's envelope (section 4). `message` is already localised. */
export class ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number
  /** Seconds to wait before trying again, from the `Retry-After` header (for example on 429). */
  readonly retryAfter: number | null

  constructor(status: number, envelope: ErrorEnvelope['error'], retryAfter: number | null = null) {
    super(envelope.message)
    this.name = 'ApiError'
    this.code = envelope.code
    this.retryable = envelope.retryable
    this.status = status
    this.retryAfter = retryAfter
  }
}

/** `Retry-After` as seconds from now: either delay-seconds or an HTTP date. Null when absent or unreadable. */
export function parseRetryAfter(header: string | null, now: number = Date.now()): number | null {
  if (!header) return null
  const value = header.trim()
  if (/^\d+$/.test(value)) return Number(value)
  const date = Date.parse(value)
  if (Number.isNaN(date)) return null
  return Math.max(0, Math.ceil((date - now) / 1000))
}

export function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = (body as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}
