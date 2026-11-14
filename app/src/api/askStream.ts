// Turns the raw /api/ask event stream into validated events (contract section 7.2).
// A payload that does not have its event's shape stops the answer with a retryable error,
// so the screen never renders half-understood data. Unknown event names are skipped: the core
// may add events in a minor version (contract section 1, unknown fields).
import { ApiError, isErrorEnvelope } from './errors.ts'
import { readSse, type SseMessage } from './sse.ts'
import type { AskEvent } from './types.ts'

type Json = Record<string, unknown>

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const isString = (value: unknown): value is string => typeof value === 'string'
const isStringOrNull = (value: unknown) => value === null || isString(value)
const isStringArray = (value: unknown) => Array.isArray(value) && value.every(isString)

/** The fields of a Number object (contract 2.1) the app reads. */
function isNumber(value: unknown): boolean {
  return (
    isObject(value) &&
    isString(value.display) &&
    isString(value.label) &&
    isString(value.method) &&
    isStringOrNull(value.evidence_ref)
  )
}

function isCard(value: unknown): boolean {
  return (
    isObject(value) &&
    isString(value.card_id) &&
    isString(value.type) &&
    isString(value.title) &&
    (value.actions === undefined || Array.isArray(value.actions))
  )
}

const VALID: Record<AskEvent['event'], (data: Json) => boolean> = {
  meta: (d) => isString(d.answer_id) && isString(d.conversation_id) && isString(d.language) && isString(d.as_of),
  status: (d) => isString(d.stage) && isStringOrNull(d.tool ?? null) && isString(d.label),
  card: (d) => isCard(d.card),
  numbers: (d) => isObject(d.numbers) && Object.values(d.numbers).every(isNumber),
  delta: (d) => isString(d.text),
  done: (d) =>
    isString(d.answer_id) &&
    isString(d.outcome) &&
    isString(d.text) &&
    isString(d.text_rendered) &&
    isStringArray(d.cited) &&
    isStringArray(d.follow_ups) &&
    isStringArray(d.warnings) &&
    (d.lesson === null || (isObject(d.lesson) && isString(d.lesson.title) && isString(d.lesson.text))) &&
    (d.refusal === null || (isObject(d.refusal) && isString(d.refusal.kind) && isString(d.refusal.label))) &&
    (d.clarify === null || (isObject(d.clarify) && isString(d.clarify.question) && isStringArray(d.clarify.options))),
  error: (d) => isErrorEnvelope(d) && typeof (d.error as Json).retryable === 'boolean',
}

/** A stream that breaks the contract. The screen shows the app's own text for this code. */
export function badStream(detail: string): ApiError {
  const error = new ApiError(200, { code: 'bad_stream', message: 'Something went wrong. Try again.', retryable: true })
  error.cause = detail
  return error
}

/** Validates one raw event; `null` means "not an /api/ask event, skip it". */
export function toAskEvent(message: SseMessage): AskEvent | null {
  if (!(message.event in VALID)) return null
  const name = message.event as AskEvent['event']
  let data: unknown
  try {
    data = JSON.parse(message.data)
  } catch {
    throw badStream(`${name}: payload is not JSON`)
  }
  if (!isObject(data) || !VALID[name](data)) throw badStream(`${name}: payload has the wrong shape`)
  return { event: name, data } as AskEvent
}

/**
 * Reads /api/ask events until `done` or `error`, then closes the stream. A stream that ends
 * without either is an error too (retryable), because the answer is incomplete.
 */
export async function* readAskStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<AskEvent> {
  for await (const message of readSse(stream)) {
    const event = toAskEvent(message)
    if (!event) continue
    yield event
    if (event.event === 'done' || event.event === 'error') return
  }
  throw new ApiError(200, { code: 'stream_ended', message: 'The answer was cut off. Try again.', retryable: true })
}
