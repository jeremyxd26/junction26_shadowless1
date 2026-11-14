// The thread's turns (#319). An ask turn is a question and its POST /api/ask answer. A client turn
// never calls the API. It holds the user's tapped chip and a Sentti turn drawn by a registered
// client component (`components/clientTurns.tsx`), for example the bill flow.
import type { Answer } from './answer.ts'

/** A question sent to `/api/ask` and its answer as it streams in. */
export interface AskTurn {
  kind: 'ask'
  id: number
  question: string
  answer: Answer
}

/**
 * A turn drawn by the app itself. It has no answer, no `answer_id` and no `meta`. It is never sent
 * to the server and never changes the conversation.
 */
export interface ClientTurn {
  kind: 'client'
  id: number
  /** One client turn per key: a second tap on the same chip brings the first turn back. */
  key: string
  /** The tapped chip's text, shown as the user's bubble. */
  question: string
  /** The registry key of the component that draws Sentti's part. */
  render: string
}

export type Turn = AskTurn | ClientTurn

/** What a chip asks for: the user's bubble, the registered component and the dedupe key. */
export interface ClientTurnRequest {
  question: string
  render: string
  id: string
}

export function isClientTurn(turn: Turn): turn is ClientTurn {
  return turn.kind === 'client'
}

/** The client turn with `key`, if the thread has one. */
export function findClientTurn(turns: Turn[], key: string): ClientTurn | undefined {
  return turns.find((turn): turn is ClientTurn => isClientTurn(turn) && turn.key === key)
}

/**
 * The thread with `turn` added at the end. When a client turn with the same key is already there,
 * the thread comes back unchanged (the same array). Ask turns are never touched.
 */
export function pushClientTurn(turns: Turn[], turn: ClientTurn): Turn[] {
  if (findClientTurn(turns, turn.key)) return turns
  return [...turns, turn]
}
