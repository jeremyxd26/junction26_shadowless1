import { describe, expect, it } from 'vitest'
import type { AskDone, Card, SafeToSaveCard } from '../types.ts'
import contract from './contract-examples.json'
import { pickStream } from './mockAsk.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const saveCard = examples['card.safe_to_save'] as SafeToSaveCard

/** The events of a stream as `[event, data]` pairs. */
function events(parts: string[]): [string, unknown][] {
  return parts.map((part) => {
    const name = /^event: (\w+)$/m.exec(part)?.[1] ?? ''
    const data = part.includes('data: ') ? JSON.parse(part.slice(part.indexOf('data: ') + 6)) : null
    return [name, data]
  })
}

function cards(parts: string[]): Card[] {
  return events(parts)
    .filter(([name]) => name === 'card')
    .map(([, data]) => (data as { card: Card }).card)
}

describe('mock ask: "How could I save more?" (#495)', () => {
  for (const question of ['How could I save more?', 'Miten voisin säästää enemmän?', 'how could i save more']) {
    it(`answers "${question}" with the contract's safe-to-save card and its host-screen action`, () => {
      const stream = pickStream(question, null)
      expect(cards(stream)).toEqual([saveCard])
      const action = saveCard.actions.find((candidate) => candidate.type === 'open_host_screen')
      expect(action).toMatchObject({ type: 'open_host_screen', target: 'monthly_saving' })
      const done = events(stream).find(([name]) => name === 'done')?.[1] as AskDone
      // The one sentence is the card's own estimate text: nothing is written by the mock.
      expect(done.text).toBe(saveCard.estimate?.text)
      expect(done.text).not.toMatch(/\d/)
      expect(done.outcome).toBe('answered')
      expect(done.follow_ups).not.toContain('How could I save more?')
    })
  }

  it('keeps the other questions on their streams', () => {
    expect(pickStream('Where did my money go?', null)).toEqual(
      (examples['ask.sse.stream'] as string)
        .trim()
        .split(/\n\n+/)
        .filter((part) => part.length > 0),
    )
    expect(cards(pickStream('Where did my money go?', null)).some((card) => card.type === 'safe_to_save')).toBe(false)
  })
})
