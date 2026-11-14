// The chat's turns and the one running /api/ask stream. It lives in App, so the conversation
// survives a trip to the overview and back; switching persona starts an empty chat. Client turns
// (#319) sit in the same list but never call the API: `busy`, `stop` and `retry` skip them.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ask } from '../api/ask.ts'
import { readAskStream } from '../api/askStream.ts'
import { ApiError } from '../api/errors.ts'
import type { Language } from '../api/types.ts'
import { EMPTY_ANSWER, applyAskEvent, type Answer, type AnswerError } from './answer.ts'
import { findClientTurn, pushClientTurn, type ClientTurnRequest, type Turn } from './thread.ts'

export type { Turn } from './thread.ts'

/** Where a chip's client turn is: a new one, or the one the same key already pushed. */
export interface PushedClientTurn {
  id: number
  existed: boolean
}

export interface ChatSession {
  turns: Turn[]
  busy: boolean
  send(question: string): void
  retry(turnId: number, question: string): void
  stop(): void
  /** Adds a client turn, or finds the one with the same `id`; null without a persona. */
  pushClientTurn(request: ClientTurnRequest): PushedClientTurn | null
}

/** The contract caps a question at 500 characters (section 7.1). */
export const MAX_QUESTION = 500

interface Session {
  owner: string | null
  turns: Turn[]
}

function toAnswerError(error: unknown): AnswerError {
  if (error instanceof ApiError) return { code: error.code, message: error.message, retryable: error.retryable }
  return { code: 'internal', message: 'Something went wrong. Try again.', retryable: true }
}

export function useChat(customerId: string | null, lang: Language): ChatSession {
  const [session, setSession] = useState<Session>({ owner: customerId, turns: [] })
  const conversation = useRef<{ owner: string | null; id: string | null }>({ owner: customerId, id: null })
  const running = useRef<{ turnId: number; controller: AbortController } | null>(null)
  const nextId = useRef(1)

  // A different persona means a different customer: its chat starts empty (derived, no effect).
  const turns = session.owner === customerId ? session.turns : []
  const busy = turns.some((turn) => turn.kind === 'ask' && turn.answer.status === 'streaming')
  // The turns as last shown, so `pushClientTurn` keeps one identity while answers stream in.
  const shownTurns = useRef(turns)
  useEffect(() => {
    shownTurns.current = turns
  })

  const update = useCallback((owner: string | null, turnId: number, change: (answer: Answer) => Answer) => {
    setSession((current) =>
      current.owner !== owner
        ? current
        : {
            ...current,
            turns: current.turns.map((turn) =>
              turn.kind === 'ask' && turn.id === turnId ? { ...turn, answer: change(turn.answer) } : turn,
            ),
          },
    )
  }, [])

  /** Stops the running stream; what was shown stays, marked as stopped. */
  const stopRunning = useCallback(() => {
    const current = running.current
    if (!current) return
    running.current = null
    current.controller.abort()
    setSession((state) => ({
      ...state,
      turns: state.turns.map((turn) =>
        turn.kind === 'ask' && turn.id === current.turnId && turn.answer.status === 'streaming'
          ? { ...turn, answer: { ...turn.answer, status: 'stopped' } }
          : turn,
      ),
    }))
  }, [])

  const run = useCallback(
    async (owner: string, turnId: number, question: string) => {
      stopRunning()
      const controller = new AbortController()
      running.current = { turnId, controller }
      if (conversation.current.owner !== owner) conversation.current = { owner, id: null }
      try {
        const stream = await ask(
          { customer_id: owner, conversation_id: conversation.current.id, message: question, language: lang },
          controller.signal,
        )
        for await (const event of readAskStream(stream)) {
          if (controller.signal.aborted) break
          if (event.event === 'meta' && conversation.current.owner === owner) {
            conversation.current = { owner, id: event.data.conversation_id }
          }
          update(owner, turnId, (answer) => applyAskEvent(answer, event))
        }
      } catch (error) {
        if (controller.signal.aborted) return
        update(owner, turnId, (answer) => ({ ...answer, status: 'error', error: toAnswerError(error) }))
      } finally {
        if (running.current?.controller === controller) running.current = null
      }
    },
    [lang, stopRunning, update],
  )

  const send = useCallback(
    (raw: string) => {
      const question = raw.trim().slice(0, MAX_QUESTION)
      if (!question || !customerId) return
      const id = nextId.current
      nextId.current += 1
      setSession((current) => ({
        owner: customerId,
        turns: [...(current.owner === customerId ? current.turns : []), { kind: 'ask', id, question, answer: EMPTY_ANSWER }],
      }))
      void run(customerId, id, question)
    },
    [customerId, run],
  )

  const retry = useCallback(
    (turnId: number, question: string) => {
      if (!customerId || !shownTurns.current.some((turn) => turn.kind === 'ask' && turn.id === turnId)) return
      update(customerId, turnId, () => EMPTY_ANSWER)
      void run(customerId, turnId, question)
    },
    [customerId, run, update],
  )

  // A client turn leaves the running answer and the conversation alone: nothing is sent.
  const pushClient = useCallback(
    (request: ClientTurnRequest): PushedClientTurn | null => {
      if (!customerId) return null
      const existing = findClientTurn(shownTurns.current, request.id)
      if (existing) return { id: existing.id, existed: true }
      const id = nextId.current
      nextId.current += 1
      const turn = { kind: 'client', id, key: request.id, question: request.question, render: request.render } as const
      setSession((current) => ({
        owner: customerId,
        turns: pushClientTurn(current.owner === customerId ? current.turns : [], turn),
      }))
      return { id, existed: false }
    },
    [customerId],
  )

  return { turns, busy, send, retry, stop: stopRunning, pushClientTurn: pushClient }
}
