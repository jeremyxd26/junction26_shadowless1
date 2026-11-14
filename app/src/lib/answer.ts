// One answer of the chat, built event by event from the /api/ask stream (contract section 7.2).
// Pure functions, so the screen and the tests share them.
import type { Action, AskDone, AskEvent, AskMeta, Card, Num } from '../api/types.ts'

export type AnswerStatus = 'streaming' | 'done' | 'error' | 'stopped'

/**
 * Why an answer stopped (#715): the Stop button (`you`), or a new question while it streamed
 * (`next_question`), since one answer streams at a time. The answer says which, so it never claims
 * the user pressed Stop when they only asked something else.
 */
export type StopReason = 'you' | 'next_question'

/** The three waiting stages, in order. A `status` event names its stage. */
export const STAGES = ['understanding', 'tool', 'writing'] as const
export type StageKey = (typeof STAGES)[number]

export interface AnswerError {
  code: string
  message: string
  retryable: boolean
}

export interface Answer {
  status: AnswerStatus
  meta: AskMeta | null
  /** The furthest stage reached: 0 understanding, 1 tool, 2 writing. */
  stage: number
  /** The label of the latest `status` event per stage; null shows the app's own label. */
  labels: Record<StageKey, string | null>
  cards: Card[]
  numbers: Record<string, Num>
  /** The text so far, with number tokens; after `done`, the full text of `done`. */
  text: string
  done: AskDone | null
  error: AnswerError | null
  /** Set with `status: 'stopped'`. */
  stoppedBy?: StopReason
}

export const EMPTY_ANSWER: Answer = {
  status: 'streaming',
  meta: null,
  stage: 0,
  labels: { understanding: null, tool: null, writing: null },
  cards: [],
  numbers: {},
  text: '',
  done: null,
  error: null,
}

const WRITING = STAGES.indexOf('writing')

export function applyAskEvent(answer: Answer, event: AskEvent): Answer {
  switch (event.event) {
    case 'meta':
      return { ...answer, meta: event.data }
    case 'status': {
      const index = STAGES.indexOf(event.data.stage as StageKey)
      if (index === -1) return answer
      return {
        ...answer,
        stage: Math.max(answer.stage, index),
        labels: { ...answer.labels, [STAGES[index]]: event.data.label },
      }
    }
    case 'card': {
      const card = event.data.card
      const cards = answer.cards.some((known) => known.card_id === card.card_id)
        ? answer.cards.map((known) => (known.card_id === card.card_id ? card : known))
        : [...answer.cards, card]
      return { ...answer, cards }
    }
    case 'numbers':
      return { ...answer, stage: Math.max(answer.stage, WRITING), numbers: { ...answer.numbers, ...event.data.numbers } }
    case 'delta':
      return { ...answer, stage: Math.max(answer.stage, WRITING), text: answer.text + event.data.text }
    case 'done':
      return { ...answer, status: 'done', done: event.data, text: event.data.text }
    case 'error':
      return { ...answer, status: 'error', error: event.data.error }
  }
}

/**
 * Holds back a number token that is not complete yet ("{{n1" at the end), so a chip never
 * shows half a token. The contract never splits a token across deltas; this guards finer
 * streaming later.
 */
export function withoutPartialToken(text: string): string {
  return text.replace(/\{(\{(n([0-9]+\}?)?)?)?$/, '')
}

/**
 * A sentence ends at `.`, `!` or `?` and whitespace, but only when the next sentence starts with
 * a capital letter or a number token. So abbreviations such as "esim. ruokaan" or "approx. three"
 * do not cut the takeaway short.
 */
const SENTENCE_END = /(?<=[.!?])\s+(?=\p{Lu}|\{\{)/u

/**
 * The answer shape: the first sentence is the bold takeaway, the rest is the explanation.
 * The contract has no separate takeaway field, so the app takes the first sentence of `text`.
 */
export function splitTakeaway(text: string): { takeaway: string; rest: string } {
  const visible = withoutPartialToken(text)
  const match = SENTENCE_END.exec(visible)
  if (!match) return { takeaway: visible.trim(), rest: '' }
  return { takeaway: visible.slice(0, match.index).trim(), rest: visible.slice(match.index + match[0].length).trim() }
}

/**
 * The answer's text came from the question's template because the AI model was not used
 * (`warnings` has `llm_unavailable`, contract section 7.2), whatever the outcome. The numbers are
 * the same either way; the app shows a quiet note.
 */
export function writtenByTemplate(done: AskDone | null): boolean {
  return done?.warnings?.includes('llm_unavailable') ?? false
}

/**
 * The actions of `done` (contract 0.3.3): every refusal, the "not yet" answer and the fallback
 * carry `contact_bank`. Entries without a string `type` and `label` are dropped; the chip renders
 * only the types and targets it knows.
 */
export function doneActions(done: AskDone | null): Action[] {
  const list = done?.actions
  if (!Array.isArray(list)) return []
  return list.filter(
    (action): action is Action =>
      typeof action === 'object' && action !== null && typeof action.type === 'string' && typeof action.label === 'string',
  )
}

/** The card actions shown as action chips under the explanation: at most 2 per card, no repeats. */

export function actionsOf(cards: Card[]): Card['actions'] {
  const seen = new Set<string>()
  const actions: Card['actions'] = []
  for (const card of cards) {
    for (const action of (card.actions ?? []).slice(0, 2)) {
      const key = `${action.type}|${action.label}`
      if (seen.has(key)) continue
      seen.add(key)
      actions.push(action)
    }
  }
  return actions
}

/** A streaming answer, stopped for `reason`; what it showed so far stays. Any other answer is left as it is. */
export function stopped(answer: Answer, reason: StopReason): Answer {
  return answer.status === 'streaming' ? { ...answer, status: 'stopped', stoppedBy: reason } : answer
}
