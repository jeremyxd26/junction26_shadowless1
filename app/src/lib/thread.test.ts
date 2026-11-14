import { describe, expect, it } from 'vitest'
import { EMPTY_ANSWER, applyAskEvent } from './answer.ts'
import { findClientTurn, isClientTurn, pushClientTurn, type AskTurn, type ClientTurn, type Turn } from './thread.ts'

const meta = { answer_id: 'ans_1', conversation_id: 'conv_1', language: 'en' as const, as_of: '2026-09-30' }
const asked: AskTurn = {
  kind: 'ask',
  id: 1,
  question: 'Where did my money go?',
  answer: applyAskEvent(EMPTY_ANSWER, { event: 'meta', data: meta }),
}
const bill: ClientTurn = { kind: 'client', id: 2, key: 'bill', question: 'Show Sentti a bill', render: 'bill' }

describe('client turns in the thread (#319)', () => {
  it('adds a client turn at the end and tells it apart from an ask turn', () => {
    const turns = pushClientTurn([asked], bill)
    expect(turns).toEqual([asked, bill])
    expect(turns.map(isClientTurn)).toEqual([false, true])
  })

  it('gives a client turn no answer, no answer_id and no meta, so nothing of it reaches the server', () => {
    const [, turn] = pushClientTurn([asked], bill)
    expect(Object.keys(turn).sort()).toEqual(['id', 'key', 'kind', 'question', 'render'])
    expect(turn).not.toHaveProperty('answer')
    expect(JSON.stringify(turn)).not.toMatch(/answer_id|conversation_id|meta/)
  })

  it('does not change the ask turns or the conversation_id they carry', () => {
    const before: Turn[] = [asked]
    const turns = pushClientTurn(before, bill)
    expect(before).toEqual([asked])
    expect(turns[0]).toBe(asked)
    const [first] = turns
    expect(first.kind === 'ask' && first.answer.meta?.conversation_id).toBe('conv_1')
  })

  it('keeps one client turn per key: a second push returns the same thread', () => {
    const once = pushClientTurn([asked], bill)
    const twice = pushClientTurn(once, { ...bill, id: 3 })
    expect(twice).toBe(once)
    expect(findClientTurn(twice, 'bill')?.id).toBe(2)
    expect(findClientTurn(twice, 'guess')).toBeUndefined()
  })

  it('lets two different client turns live side by side', () => {
    const guess: ClientTurn = { kind: 'client', id: 3, key: 'guess', question: 'Let me guess first', render: 'guess' }
    expect(pushClientTurn(pushClientTurn([asked], bill), guess).map((turn) => turn.id)).toEqual([1, 2, 3])
  })
})
