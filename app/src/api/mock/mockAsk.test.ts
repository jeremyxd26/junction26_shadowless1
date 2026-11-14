import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AskDone, BasketKey, Card, MetricCard, OverviewResponse, SafeToSaveCard } from '../types.ts'
import contract from './contract-examples.json'
import { pickStream } from './mockAsk.ts'
import { createMockClient } from './mockClient.ts'

const examples = contract.examples as unknown as Record<string, unknown>
/** Sanna's overview before the review answer: the persona pickStream answers for without a customer. */
const pending = examples['overview.response_pending'] as OverviewResponse
const aino = examples['overview.response'] as OverviewResponse
const saveCard = pending.safe_to_save!

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
    it(`answers "${question}" with the overview's safe-to-save card and its host-screen action`, () => {
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

describe('mock ask: Finnish chips with lang=fi (#374)', () => {
  const doneOf = (parts: string[]) => events(parts).find(([name]) => name === 'done')?.[1] as AskDone
  const finnish = examples['ask.json.response_fi'] as { follow_ups: string[]; text_rendered: string }

  it("answers a Finnish request without its own example with the contract's Finnish answer and its Finnish follow-ups", () => {
    const done = doneOf(pickStream('Where did my money go?', null, true, 'fi'))
    expect(done.follow_ups).toEqual(finnish.follow_ups)
    expect(done.text_rendered).toBe(finnish.text_rendered)
  })

  it('keeps English requests on the English stream', () => {
    const done = doneOf(pickStream('Where did my money go?', null, true, 'en'))
    expect(done.follow_ups.join(' ')).not.toMatch(/[äöÄÖ]/)
    expect(done.follow_ups).not.toEqual(finnish.follow_ups)
  })

  it("keeps the questions that have their own example on it, whatever the language", () => {
    expect(cards(pickStream('Miten voisin säästää enemmän?', null, true, 'fi'))).toEqual([saveCard])
  })
})

describe("mock ask: an answer's numbers are the ones on screen, before and after the review answer (#714)", () => {
  const SANNA = 'CUST00860'
  const api = createMockClient()
  const label = (basket: BasketKey | null) =>
    api.label({ customer_id: SANNA, tx_ref: pending.reviews[0].tx_ref, basket, language: 'en' })
  const spend = (customer = SANNA) => cards(pickStream('What can I safely spend this week?', null, true, 'en', customer))[0] as MetricCard
  const save = (customer = SANNA) => cards(pickStream('How could I save more?', null, true, 'en', customer))[0] as SafeToSaveCard
  const saving = (card: SafeToSaveCard) => [card.monthly, card.weekly, card.daily].map((number) => number?.display)
  const rows = (card: MetricCard) => card.secondary.map((number) => number.display)

  // The mock keeps the answer for the page load: each test ends without one.
  afterEach(async () => {
    await label(null)
    vi.unstubAllGlobals()
  })

  it("before any answer: the hero's €138.79 and the sheet's €364.31 · €83.78 · €11.97", async () => {
    const overview = await api.overview(SANNA, 'en')
    expect(spend()).toEqual(overview.hero)
    expect(spend().primary.display).toBe('€138.79')
    expect(save()).toEqual(overview.safe_to_save)
    expect(saving(save())).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
  })

  it('Needed: the answered €97.46 and €184.61 · €42.46 · €6.07; Undo brings the pending ones back', async () => {
    await label('unexpected_necessities')
    const answered = await api.overview(SANNA, 'en')
    expect(spend()).toEqual(answered.hero)
    expect(spend().primary.display).toBe('€97.46')
    // No pending figure under the new number ("Your monthly budget allows €138.79"): only free until
    // payday has an after-state example (the contract's after-state safe-to-save card).
    expect(rows(spend())).toEqual(['€12,567.56'])
    expect(save()).toEqual(answered.safe_to_save)
    expect(saving(save())).toEqual(['€184.61 a month', '€42.46 a week', '€6.07 a day'])
    // What the month is based on, and "How is this calculated?", are the after-state's too.
    expect(save().estimate?.observed?.map((number) => number.display)).toEqual(['€783.79 a month', '€599.18 a month'])
    expect(save().actions.find((action) => action.type === 'open_evidence')).toMatchObject({ evidence_ref: save().monthly.evidence_ref })

    await label(null)
    expect(spend()).toEqual(pending.hero)
    expect(save()).toEqual(pending.safe_to_save)
    expect(saving(save())).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
  })

  it('My choice moves neither number, so both answers keep the pending figures', async () => {
    await label('everyday_spending')
    const answered = await api.overview(SANNA, 'en')
    expect(spend()).toEqual(answered.hero)
    expect(spend().primary.display).toBe('€138.79')
    expect(rows(spend())).toEqual(rows(pending.hero!))
    expect(save()).toEqual(answered.safe_to_save)
    expect(saving(save())).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
  })

  it('after Undo, an older answer still opens its numbers (Needed’s €97.46)', async () => {
    await label('unexpected_necessities')
    const older = spend()
    await label(null)
    for (const number of [older.primary, ...older.secondary]) {
      const evidence = await api.evidence(number.evidence_ref!, SANNA, 'en')
      expect(evidence.number.display).toBe(number.display)
    }
  })

  it("Aino: her own hero (€184.68) and safe-to-save card (€431.58), not Sanna's", () => {
    expect(spend('CUST00042')).toEqual(aino.hero)
    expect(spend('CUST00042').primary.display).toBe('€184.68')
    expect(save('CUST00042')).toEqual(aino.safe_to_save)
    expect(save('CUST00042').monthly.display).toBe('€431.58 a month')
  })

  it('?mock=no_hero: no safe-to-spend card from somewhere else; the question is answered like any other', () => {
    vi.stubGlobal('window', { location: new URL('http://localhost/?mock=no_hero') })
    const stream = pickStream('What can I safely spend this week?', null, true, 'en', 'CUST00042')
    expect(cards(stream).some((card) => card.type === 'metric')).toBe(false)
    expect(stream).toEqual(pickStream('Where did my money go?', null, true, 'en', 'CUST00042'))
  })
})
