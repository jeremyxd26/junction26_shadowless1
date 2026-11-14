// Mock POST /api/ask: replays the contract's examples as a text/event-stream byte stream with
// realistic delays, so the chat runs through the same parser as in live mode.
//
// Which stream answers which question (all from contracts/api.md section 7):
// - the contract's refusal question, or any question about stocks or investing: the refusal
//   example (`ask.json.response_refusal`), turned into stream events;
// - the contract's clarify question ("How much did I spend?"): `ask.json.response_clarify`;
// - the contract's Finnish question: `ask.json.response_fi`;
// - anything else: the full stream `ask.sse.stream`, unchanged.
// `?mock=error` in the page URL plays `ask.sse.stream_error`. The contract has no examples for
// the two model-off cases (section 7.2, PR #261), so they are built from the full stream's meta,
// status and card:
// - `?mock=template`: the AI model was not used, so the template answered: the template line
//   "Here is what I found for September." (section 7.5), `outcome: "answered"` and the
//   `llm_unavailable` warning;
// - `?mock=fallback`: even the template failed the answer check: the fixed short text
//   "I could not find data for that question.", `outcome: "fallback"`, no warning.
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
  'ask.json.response_refusal_first': AskJsonResponse
  'ask.json.request_clarify': AskRequest
  'ask.json.response_clarify': AskJsonResponse
  'error.response': ErrorEnvelope
  'card.review': Card
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
    actions: response.actions ?? [],
    ai_disclosure: response.ai_disclosure ?? null,
  }
  blocks.push(block('done', done))
  return blocks
}

/** The question's template line when the AI model is not used (contract section 7.5). */
const TEMPLATE_TEXT = 'Here is what I found for September.'
/** The core's fixed short text when even the template failed the answer check (section 7.2). */
const FALLBACK_TEXT = 'I could not find data for that question.'

/** The full stream's cards, then `text` as the only delta and a `done` with `outcome` and `warnings`. */
function cardsWithText(text: string, outcome: AskDone['outcome'], warnings: AskDone['warnings']): string[] {
  const full = blocksOf(examples['ask.sse.stream'])
  const upToCards = full.filter((part) => /^event: (meta|status|card)$/m.test(part))
  const done: AskDone = {
    ...examples['ask.sse.done'],
    outcome,
    text,
    text_rendered: text,
    cited: [],
    lesson: null,
    warnings,
  }
  return [...upToCards, block('delta', { text }), block('done', done)]
}

/** The AI model was not used: the template answered (`answered` with `llm_unavailable`). */
const templateStream = () => cardsWithText(TEMPLATE_TEXT, 'answered', ['llm_unavailable'])
/** Even the template failed the answer check: the fixed short text (`fallback`). */
const fallbackStream = () => cardsWithText(FALLBACK_TEXT, 'fallback', [])

/** `?mock=review`: the full stream with the contract's `card.review` after its card (#450). */
function reviewStream(): string[] {
  const full = blocksOf(examples['ask.sse.stream'])
  const at = full.findIndex((part) => /^event: card$/m.test(part)) + 1
  return [...full.slice(0, at), block('card', { card: examples['card.review'] }), ...full.slice(at)]
}

function normalise(message: string): string {
  return message.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

const sameQuestion = (message: string, request: AskRequest) => normalise(message) === normalise(request.message)

function pickStream(message: string, scenario: string | null, first = true): string[] {
  if (scenario === 'error') return blocksOf(examples['ask.sse.stream_error'])
  if (scenario === 'template') return templateStream()
  if (scenario === 'fallback') return fallbackStream()
  if (scenario === 'review') return reviewStream()
  if (sameQuestion(message, examples['ask.json.request_refusal']) || /\b(stock|stocks|shares|invest\w*|osak\w*|sijoit\w*)\b/.test(normalise(message))) {
    // The first answer of a conversation carries the AI disclosure (0.3.3).
    return streamOfJson(examples[first ? 'ask.json.response_refusal_first' : 'ask.json.response_refusal'])
  }
  if (sameQuestion(message, examples['ask.json.request_clarify'])) return streamOfJson(examples['ask.json.response_clarify'])
  if (sameQuestion(message, examples['ask.json.request_fi'])) return streamOfJson(examples['ask.json.response_fi'])
  // `?mock=refusal`: the refusal with the contact_bank chip, whatever the question.
  if (scenario === 'refusal') return streamOfJson(examples[first ? 'ask.json.response_refusal_first' : 'ask.json.response_refusal'])
  return blocksOf(examples['ask.sse.stream'])
}

/** The AI disclosure only on the first answer of a conversation, as the core sends it (0.3.3). */
function onlyFirstDiscloses(blocks: string[], first: boolean): string[] {
  if (first) return blocks
  return blocks.map((part) => {
    if (eventName(part) !== 'done') return part
    const data = JSON.parse(part.slice(part.indexOf('data: ') + 6)) as AskDone
    return block('done', { ...data, ai_disclosure: null })
  })
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
  const first = !request.conversation_id
  return wireStream(onlyFirstDiscloses(pickStream(request.message, scenario, first), first), scenario === 'slow' ? 4 : 1, signal)
}
