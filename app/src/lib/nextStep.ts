// The one next step under an answer (#684), taken from what the response already carries. Order:
// 0. a refusal: only its own action, the way to a human, or nothing (#696);
// 1. the answer's own action (`done.actions`, contract 0.3.3: the way to a human); for a fallback
//    and the "not yet" answer, their questions come before it on the latest answer (#696);
// 2. a card action that leads somewhere: the what-if, the bank's own screen (S-mobiili's monthly
//    saving, which the demo path taps), or a question;
// 3. the first follow-up question (the thread shows it on the latest answer only, as before);
// 4. a card's "how is this calculated" (the numbers open the same evidence when tapped).
// Nothing is invented: with none of these there is no next step. A clarification's options are
// its answer, so it offers only its own action.
import type { Action, AskDone, Card } from '../api/types.ts'
import { actionsOf, doneActions } from './answer.ts'
import { hostScreenTarget } from './hostActions.ts'

export type NextStep = { kind: 'action'; action: Action } | { kind: 'question'; question: string }

/** An action the app can carry out; a host screen it does not know would draw nothing. */
function usable(action: Action): boolean {
  if (action.type === 'open_host_screen') return hostScreenTarget(action.target) !== null
  return action.type === 'open_evidence' || action.type === 'ask' || action.type === 'open_whatif'
}

/**
 * `latest`: whether this is the thread's latest answer. Follow-up questions (and a "not yet"
 * answer's options) show only there; on an older answer they are hidden, so the step falls back
 * to the answer's own way to a human when it has one.
 */
export function nextStep(done: AskDone | null, cards: Card[], latest = true): NextStep | null {
  if (!done) return null
  const own = doneActions(done).filter(usable)
  const way: NextStep | null = own.length > 0 ? { kind: 'action', action: own[0] } : null
  // A refusal: only the way to a human, or nothing (#696).
  if (done.outcome === 'refused') return way
  const firstQuestion = done.follow_ups?.find((text) => typeof text === 'string' && text.trim())
  // Maxim's decision on #696: the "nothing found" fallback and the "I can't answer that one yet"
  // answer (a clarification that carries the way to a human, contract 7.2) go on with their own
  // questions; the way to a human only when there are none. The core sends the "not yet"
  // questions as `clarify.options` with `follow_ups: []`: those options are its follow-ups, and
  // the thread shows them as chips (coordinator's ruling on #710).
  const notYet = done.outcome === 'clarify' && own.length > 0
  if (done.outcome === 'fallback' || notYet) {
    const options = notYet ? (done.clarify?.options ?? []).filter((text) => typeof text === 'string' && text.trim()) : []
    if (latest && options.length > 0) return null
    if (latest && firstQuestion) return { kind: 'question', question: firstQuestion }
    return way
  }
  if (way) return way
  if (done.outcome === 'clarify') return null
  const cardActions = actionsOf(cards).filter(usable)
  const leading = cardActions.find((action) => action.type !== 'open_evidence')
  if (leading) return { kind: 'action', action: leading }
  // A follow-up only on the latest answer; an older one shows none (as before #696).
  if (firstQuestion) return latest ? { kind: 'question', question: firstQuestion } : null
  const evidence = cardActions.find((action) => action.type === 'open_evidence')
  return evidence ? { kind: 'action', action: evidence } : null
}
