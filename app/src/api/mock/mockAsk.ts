// Mock POST /api/ask: replays the contract's examples as a text/event-stream byte stream with
// realistic delays, so the chat runs through the same parser as in live mode.
//
// Which stream answers which question (all from contracts/api.md section 7):
// - the contract's refusal question, or any question about stocks or investing: the refusal
//   example (`ask.json.response_refusal`), turned into stream events;
// - the contract's clarify question ("How much did I spend?"): `ask.json.response_clarify`;
// - the contract's Finnish question: `ask.json.response_fi`;
// - "How could I save more?" / "Miten voisin säästää enemmän?" (the partner's fourth question):
//   the contract has no ask example for it, so the stream is built from examples only: the full
//   stream's meta and status, the safe-to-save card of the asking customer's overview as the mock
//   serves it now (with its "See monthly saving in S-mobiili" action), the card's own
//   `estimate.text` as the one sentence (it has no number), and the full stream's `done` with that
//   text (#495);
// - "What can I safely spend this week?", "What if I spend 20% less on restaurants?" and "What kind
//   of spender am I?" (the overview's suggested questions and the full stream's follow-ups): built
//   the same way, with the safe-to-spend card (the hero) of the overview as served now,
//   `card.whatif`, or `card.profile` and `card.peer`, and one sentence the card already carries (#684);
// The overview "as served now" (mockClient.ts `overviewNow`) is the one on the customer's screen:
// pending, after the review answer or after Undo, so the answer's numbers are the opening's and the
// overview sheet's (#714). Without that card (`?mock=no_hero`) the question is answered like any other.
// - anything else: the full stream `ask.sse.stream`, unchanged.
// `?mock=error` in the page URL plays `ask.sse.stream_error`. The contract has no examples for
// the two model-off cases (section 7.2, PR #261), so they are built from the full stream's meta,
// status and card:
// - `?mock=template`: the AI model was not used, so the template answered: the template line
//   "Here is what I found for September." (section 7.5), `outcome: "answered"` and the
//   `llm_unavailable` warning;
// - `?mock=fallback`: even the template failed the answer check: the fixed short text
//   "I could not find data for that question.", `outcome: "fallback"`, no warning, the
//   `contact_bank` action every fallback carries, and the full stream's follow-ups.
// `?mock=slow` makes every delay four times longer, to watch the waiting stages.
import { ApiError } from '../errors.ts'
import type { AskDone, AskRequest, Card, ErrorEnvelope, Num } from '../types.ts'
import contract from './contract-examples.json'
import { overviewNow } from './mockClient.ts'

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
  'card.whatif': Card
  'card.profile': Card & { profile: { description: string } }
  'card.peer': Card
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

/** The full stream's cards, then `text` as the only delta and a `done` with `outcome`, `warnings` and `actions`. */
function cardsWithText(text: string, outcome: AskDone['outcome'], warnings: AskDone['warnings'], actions: AskDone['actions'] = []): string[] {
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
    actions,
  }
  return [...upToCards, block('delta', { text }), block('done', done)]
}

/** The AI model was not used: the template answered (`answered` with `llm_unavailable`). */
const templateStream = () => cardsWithText(TEMPLATE_TEXT, 'answered', ['llm_unavailable'])
/**
 * Even the template failed the answer check: the fixed short text (`fallback`). Like every fallback
 * it carries the way to a human (contract 0.3.3), taken from the refusal example, and the full
 * stream's follow-ups, so the next step shows the follow-up first (#696).
 */
const fallbackStream = () => cardsWithText(FALLBACK_TEXT, 'fallback', [], examples['ask.json.response_refusal'].actions ?? [])

/** `?mock=review`: the full stream with the contract's `card.review` after its card (#450). */
function reviewStream(): string[] {
  const full = blocksOf(examples['ask.sse.stream'])
  const at = full.findIndex((part) => /^event: card$/m.test(part)) + 1
  return [...full.slice(0, at), block('card', { card: examples['card.review'] }), ...full.slice(at)]
}

/** The partner's question about saving, in English and Finnish (the overview's suggested question). */
const SAVE_QUESTIONS = ['How could I save more?', 'Miten voisin säästää enemmän?']

/**
 * "How could I save more?": the full stream's meta and status, then the safe-to-save card of the
 * customer's overview as served now and its `estimate.text` as the answer, with nothing written by
 * the mock (#495, #714). Null when that overview has no safe-to-save card.
 */
function saveStream(customerId: string): string[] | null {
  const card = overviewNow(customerId)?.safe_to_save
  if (!card) return null
  const text = card.estimate?.text ?? card.title
  const opening = blocksOf(examples['ask.sse.stream']).filter((part) => /^event: (meta|status)$/m.test(part))
  const done: AskDone = {
    ...examples['ask.sse.done'],
    outcome: 'answered',
    text,
    text_rendered: text,
    cited: [],
    follow_ups: examples['ask.sse.done'].follow_ups.filter((question) => !SAVE_QUESTIONS.includes(question)),
    lesson: null,
    warnings: [],
    actions: [],
  }
  return [...opening, block('card', { card }), block('delta', { text }), block('done', done)]
}

/**
 * The other route answers of the demo, built like `saveStream` from examples only: the full
 * stream's meta and status, the example card(s), one sentence the first card already carries, and
 * the full stream's `done` without the asked question in its follow-ups (#684).
 */
function routeStream(asked: string, cards: Card[], text: string): string[] {
  const opening = blocksOf(examples['ask.sse.stream']).filter((part) => /^event: (meta|status)$/m.test(part))
  const done: AskDone = {
    ...examples['ask.sse.done'],
    outcome: 'answered',
    text,
    text_rendered: text,
    cited: [],
    follow_ups: examples['ask.sse.done'].follow_ups.filter((question) => normalise(question) !== normalise(asked)),
    lesson: null,
    warnings: [],
    actions: [],
  }
  return [...opening, ...cards.map((card) => block('card', { card })), block('delta', { text }), block('done', done)]
}

/**
 * Question → its cards and the sentence they carry (an estimate's text or the profile's
 * description), or null when the customer's overview has no such card (#714).
 */
const ROUTES: Record<string, (customerId: string) => { cards: Card[]; text: string } | null> = {
  'What can I safely spend this week?': (customerId) => {
    // The hero of the overview on screen now, not another persona's or another moment's (#714).
    const hero = overviewNow(customerId)?.hero
    return hero ? { cards: [hero], text: hero.estimate?.text ?? hero.title } : null
  },
  'What if I spend 20% less on restaurants?': () => {
    const card = examples['card.whatif']
    return { cards: [card], text: card.estimate?.text ?? card.title }
  },
  'What kind of spender am I?': () => {
    const profile = examples['card.profile']
    return { cards: [profile, examples['card.peer']], text: profile.profile.description }
  },
}

function routeOf(message: string, customerId: string): string[] | null {
  const asked = Object.keys(ROUTES).find((question) => normalise(question) === normalise(message))
  const route = asked ? ROUTES[asked](customerId) : null
  return asked && route ? routeStream(asked, route.cards, route.text) : null
}

function normalise(message: string): string {
  return message.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

const sameQuestion = (message: string, request: AskRequest) => normalise(message) === normalise(request.message)

/** The demo's lead persona (Sanna), for callers that name no customer: the mock's tests. */
const DEMO_CUSTOMER = 'CUST00860'

/**
 * The stream that answers `message` (exported for the mock's tests). `language` is the request's:
 * a Finnish question without an example of its own gets the contract's Finnish answer, so its text
 * and its follow-up chips are Finnish (#374); the contract has no other Finnish answer.
 * `customerId` is the request's: the safe-to-spend and safe-to-save answers carry the cards of that
 * customer's overview as the mock serves it now (#714).
 */
export function pickStream(message: string, scenario: string | null, first = true, language?: string, customerId = DEMO_CUSTOMER): string[] {
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
  const route = routeOf(message, customerId)
  if (route) return route
  const save = SAVE_QUESTIONS.some((question) => normalise(question) === normalise(message)) ? saveStream(customerId) : null
  if (save) return save
  // `?mock=refusal`: the refusal with the contact_bank chip, whatever the question.
  if (scenario === 'refusal') return streamOfJson(examples[first ? 'ask.json.response_refusal_first' : 'ask.json.response_refusal'])
  if (language === 'fi') return streamOfJson(examples['ask.json.response_fi'])
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
  return wireStream(
    onlyFirstDiscloses(pickStream(request.message, scenario, first, request.language, request.customer_id), first),
    scenario === 'slow' ? 4 : 1,
    signal,
  )
}
