// Mock POST /api/ask: replays the contract's examples as a text/event-stream byte stream with
// realistic delays, so the chat runs through the same parser as in live mode.
//
// Which stream answers which question (all from contracts/api.md section 7):
// - the contract's refusal question, or any question about stocks or investing: the refusal
//   example (`ask.json.response_refusal`), turned into stream events;
// - the contract's clarify question ("How much did I spend?"): `ask.json.response_clarify`;
// - the contract's Finnish question: `ask.json.response_fi`;
// - anything else: the full stream `ask.sse.stream`, unchanged.
// `?mock=error` in the page URL plays `ask.sse.stream_error`, and `?mock=fallback` plays a
// fallback answer. The contract has no fallback example, so that one is built from the full
// stream: the same meta, status and card, the contract's template line "Here is what I found
// for September." (section 7.5), `outcome: "fallback"` and the `llm_unavailable` warning.
// `?mock=slow` makes every delay four times longer, to watch the waiting stages.
import { ApiError } from '../errors.ts'
import type { AskDone, AskRequest, Card, ErrorEnvelope, Num } from '../types.ts'
import contract from './contract-examples.json'

interface AskJsonResponse extends AskDone {
  conversation_id: string
  language: string
  as_of: string
  numbers: Record<string, Num>
  cards: Card[]
}

const examples = contract.examples as unknown as {
  'ask.sse.stream': string
  'ask.sse.stream_error': string
  'ask.sse.done': AskDone
  'ask.json.request_fi': AskRequest
  'ask.json.response_fi': AskJsonResponse
  'ask.json.request_refusal': AskRequest
  'ask.json.response_refusal': AskJsonResponse
  'ask.json.request_clarify': AskRequest
  'ask.json.response_clarify': AskJsonResponse
  'error.response': ErrorEnvelope
}

/** Customers with mock data; others get the contract's customer_not_found before the stream. */
const KNOWN_CUSTOMERS = new Set(['CUST00042', 'CUST00860'])

/** Milliseconds before each event, roughly as the core spends them (plan, tools, compose). */
const DELAY: Record<string, number> = {
  meta: 150,
  status: 900,
  card: 1300,
  numbers: 900,
  delta: 350,
  done: 300,
  error: 1400,
  ping: 500,
}

/** The core's sentence split for deltas (one sentence per delta in contract 0.1). */
const SENTENCE_END = /(?<=[.!?])\s+/
const TOKEN = /\{\{(n[0-9]+)\}\}/g

function block(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}`
}

/** The wire text of a contract stream example, cut into its events. */
function blocksOf(stream: string): string[] {
  return stream
    .trim()
    .split(/\n\n+/)
    .filter((part) => part.length > 0)
}

/** A JSON answer (section 7.4) as the events the stream would carry (section 7.2). */
function streamOfJson(response: AskJsonResponse): string[] {
  const blocks = [
    block('meta', {
      answer_id: response.answer_id,
      conversation_id: response.conversation_id,
      language: response.language,
      as_of: response.as_of,
    }),
    ...response.cards.map((card) => block('card', { card })),
  ]
  const sent = new Set<string>()
  const sentences = response.text.trim().split(SENTENCE_END).filter(Boolean)
  sentences.forEach((sentence, index) => {
    const piece = index < sentences.length - 1 ? `${sentence} ` : sentence
    const fresh = [...piece.matchAll(TOKEN)].map((match) => match[1]).filter((id) => !sent.has(id))
    if (fresh.length > 0) {
      fresh.forEach((id) => sent.add(id))
      blocks.push(block('numbers', { numbers: Object.fromEntries(fresh.map((id) => [id, response.numbers[id]])) }))
    }
    blocks.push(block('delta', { text: piece }))
  })
  const done: AskDone = {
    answer_id: response.answer_id,
    outcome: response.outcome,
    text: response.text,
    text_rendered: response.text_rendered,
    cited: response.cited,
    follow_ups: response.follow_ups,
    lesson: response.lesson,
    refusal: response.refusal,
    clarify: response.clarify,
    warnings: response.warnings,
  }
  blocks.push(block('done', done))
  return blocks
}

const FALLBACK_TEXT = 'Here is what I found for September.'

function fallbackStream(): string[] {
  const full = blocksOf(examples['ask.sse.stream'])
  const upToCards = full.filter((part) => /^event: (meta|status|card)$/m.test(part))
  const done: AskDone = {
    ...examples['ask.sse.done'],
    outcome: 'fallback',
    text: FALLBACK_TEXT,
    text_rendered: FALLBACK_TEXT,
    cited: [],
    lesson: null,
    warnings: ['llm_unavailable'],
  }
  return [...upToCards, block('delta', { text: FALLBACK_TEXT }), block('done', done)]
}

function normalise(message: string): string {
  return message.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

const sameQuestion = (message: string, request: AskRequest) => normalise(message) === normalise(request.message)

function pickStream(message: string, scenario: string | null): string[] {
  if (scenario === 'error') return blocksOf(examples['ask.sse.stream_error'])
  if (scenario === 'fallback') return fallbackStream()
  if (sameQuestion(message, examples['ask.json.request_refusal']) || /\b(stock|stocks|shares|invest\w*|osak\w*|sijoit\w*)\b/.test(normalise(message))) {
    return streamOfJson(examples['ask.json.response_refusal'])
  }
  if (sameQuestion(message, examples['ask.json.request_clarify'])) return streamOfJson(examples['ask.json.response_clarify'])
  if (sameQuestion(message, examples['ask.json.request_fi'])) return streamOfJson(examples['ask.json.response_fi'])
  return blocksOf(examples['ask.sse.stream'])
}

function eventName(part: string): string {
  return /^event: (\w+)$/m.exec(part)?.[1] ?? (part.startsWith(':') ? 'ping' : 'message')
}

function aborted(signal?: AbortSignal): unknown {
  return signal?.reason ?? new DOMException('The request was aborted.', 'AbortError')
}

/**
 * Sends each event after its delay. Each event goes out in two chunks, cut mid-event, so the
 * parser's chunk handling runs in the browser too. Aborting errors the stream like fetch does.
 */
function wireStream(parts: string[], slow: number, signal?: AbortSignal): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const onAbort = () => {
        clearTimeout(timer)
        if (closed) return
        closed = true
        controller.error(aborted(signal))
      }
      if (signal?.aborted) return onAbort()
      signal?.addEventListener('abort', onAbort, { once: true })
      let index = 0
      let first = true
      const next = () => {
        if (closed) return
        if (index >= parts.length) {
          closed = true
          signal?.removeEventListener('abort', onAbort)
          controller.close()
          return
        }
        const part = parts[index]
        index += 1
        const name = eventName(part)
        // Deltas after the first one follow quickly; the first waits for the composer.
        const wait = name === 'delta' && !first ? DELAY.delta : name === 'delta' ? 150 : DELAY[name] ?? 200
        if (name === 'delta') first = false
        timer = setTimeout(() => {
          if (closed) return
          const bytes = encoder.encode(`${part}\n\n`)
          const cut = Math.floor(bytes.length / 2)
          controller.enqueue(bytes.slice(0, cut))
          controller.enqueue(bytes.slice(cut))
          next()
        }, wait * slow)
      }
      next()
    },
    cancel() {
      closed = true
      clearTimeout(timer)
    },
  })
}

function scenarioFromUrl(): string | null {
  if (typeof window === 'undefined') return null
  return new URLSearchParams(window.location.search).get('mock')
}

export async function mockAsk(request: AskRequest, signal?: AbortSignal): Promise<ReadableStream<Uint8Array>> {
  await new Promise((resolve) => setTimeout(resolve, 120))
  if (signal?.aborted) throw aborted(signal)
  if (!KNOWN_CUSTOMERS.has(request.customer_id)) throw new ApiError(404, examples['error.response'].error)
  const scenario = scenarioFromUrl()
  return wireStream(pickStream(request.message, scenario), scenario === 'slow' ? 4 : 1, signal)
}
