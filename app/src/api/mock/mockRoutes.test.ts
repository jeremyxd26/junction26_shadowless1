import { describe, expect, it } from 'vitest'
import type { AskDone, Card } from '../types.ts'
import contract from './contract-examples.json'
import { pickStream } from './mockAsk.ts'

const examples = contract.examples as unknown as Record<string, unknown>

function events(parts: string[]): [string, unknown][] {
  return parts.map((part) => {
    const name = /^event: (\w+)$/m.exec(part)?.[1] ?? ''
    const data = part.includes('data: ') ? JSON.parse(part.slice(part.indexOf('data: ') + 6)) : null
    return [name, data]
  })
}

const cardsOf = (parts: string[]) =>
  events(parts)
    .filter(([name]) => name === 'card')
    .map(([, data]) => (data as { card: Card }).card)
const doneOf = (parts: string[]) => events(parts).find(([name]) => name === 'done')?.[1] as AskDone

describe('mock ask: the demo route answers (#684)', () => {
  // Sanna's hero: the overview of the persona pickStream answers for without a customer, before any
  // review answer. Per persona and per state in mockAsk.test.ts (#714).
  const hero = (examples['overview.response_pending'] as { hero: Card }).hero
  const whatif = examples['card.whatif'] as Card
  const profile = examples['card.profile'] as Card & { profile: { description: string } }
  const peer = examples['card.peer'] as Card

  const cases: [string, Card[], string][] = [
    ['What can I safely spend this week?', [hero], hero.estimate!.text],
    ['What if I spend 20% less on restaurants?', [whatif], whatif.estimate!.text],
    ['What kind of spender am I?', [profile, peer], profile.profile.description],
  ]

  for (const [question, cards, text] of cases) {
    it(`answers "${question}" with the example cards and a sentence they already carry`, () => {
      const stream = pickStream(question.toLowerCase(), null)
      expect(cardsOf(stream)).toEqual(cards)
      const done = doneOf(stream)
      expect(done.outcome).toBe('answered')
      expect(done.text).toBe(text)
      expect(done.follow_ups).not.toContain(question)
    })
  }

  it('leaves "Where did my money go?" on the full stream', () => {
    expect(cardsOf(pickStream('Where did my money go?', null)).map((card) => card.type)).toEqual(['breakdown'])
  })
})
