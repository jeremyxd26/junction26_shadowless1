// The one next step under an answer (#684), taken from what the response already carries. Order:
// 1. the answer's own action (`done.actions`, contract 0.3.3: the way to a human);
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

export function nextStep(done: AskDone | null, cards: Card[]): NextStep | null {
  if (!done) return null
  const own = doneActions(done).filter(usable)
  if (own.length > 0) return { kind: 'action', action: own[0] }
  if (done.outcome === 'clarify') return null
  // A refusal offers no card actions (as before).
  const cardActions = done.outcome === 'refused' ? [] : actionsOf(cards).filter(usable)
  const leading = cardActions.find((action) => action.type !== 'open_evidence')
  if (leading) return { kind: 'action', action: leading }
  const question = done.follow_ups?.find((text) => typeof text === 'string' && text.trim())
  if (question) return { kind: 'question', question }
  const evidence = cardActions.find((action) => action.type === 'open_evidence')
  return evidence ? { kind: 'action', action: evidence } : null
}
