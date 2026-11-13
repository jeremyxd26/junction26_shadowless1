import type { ErrorEnvelope } from './types.ts'

/** An error in the contract's envelope (section 4). `message` is already localised. */
export class ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number

  constructor(status: number, envelope: ErrorEnvelope['error']) {
    super(envelope.message)
    this.name = 'ApiError'
    this.code = envelope.code
    this.retryable = envelope.retryable
    this.status = status
  }
}

export function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = (body as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}
