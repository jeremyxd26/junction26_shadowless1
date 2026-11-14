import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LabelRequest, OverviewResponse } from '../types.ts'
import contract from './contract-examples.json'
import { createMockClient } from './mockClient.ts'

const examples = contract.examples as unknown as Record<string, { message?: { text_rendered: string } } & Partial<OverviewResponse>>
const sanna = examples['overview.response_pending'] as OverviewResponse
const txRef = sanna.reviews[0].tx_ref

const request = (basket: LabelRequest['basket'], language: LabelRequest['language'] = 'en'): LabelRequest => ({
  customer_id: 'CUST00860',
  tx_ref: txRef,
  basket,
  language,
})

describe('mock review answers: Undo matches the answer it undoes (#521)', () => {
  const api = createMockClient()

  it('My choice, then Undo: no "goes from", no numbers, its own changes reversed', async () => {
    const answer = await api.label(request('everyday_spending'))
    const undo = await api.label(request(null))
    expect(undo.review_state).toBe('pending')
    expect(undo.message.text_rendered).not.toMatch(/goes from/)
    expect(undo.message.numbers).toEqual({})
    expect(undo.message.text).toBe('Undone: safe to spend stays the same, and the purchase is waiting for your answer again.')
    expect(undo.changes.map((c) => [c.key, c.before.value, c.after.value])).toEqual(
      answer.changes.map((c) => [c.key, c.after.value, c.before.value]),
    )
    expect(undo.changes.some((c) => c.key === 'safe_to_spend')).toBe(false)
  })

  it('My choice, then Undo in Finnish: the Finnish neutral text', async () => {
    await api.label(request('everyday_spending', 'fi'))
    const undo = await api.label(request(null, 'fi'))
    expect(undo.message.text_rendered).toBe('Kumottu: käyttövara pysyy ennallaan, ja ostos odottaa taas vastaustasi.')
  })

  it('Needed, then Undo: the contract undo, safe to spend goes back up', async () => {
    await api.label(request('unexpected_necessities'))
    const undo = await api.label(request(null))
    expect(undo.message.text_rendered).toBe(examples['label.response_undo'].message!.text_rendered)
    expect(undo.changes.find((c) => c.key === 'safe_to_spend')?.after.value).toBeGreaterThan(
      undo.changes.find((c) => c.key === 'safe_to_spend')!.before.value,
    )
  })
})

describe('mock: the safe-to-save week and day follow the month after an answer (#712)', () => {
  // The mock reads `?mock=` scenarios from the page's URL.
  beforeEach(() => vi.stubGlobal('window', { location: new URL('http://localhost/?persona=CUST00860') }))
  afterEach(() => vi.unstubAllGlobals())
  const displays = (overview: OverviewResponse) =>
    [overview.safe_to_save?.monthly, overview.safe_to_save?.weekly, overview.safe_to_save?.daily].map((n) => n?.display)

  it('Needed: the contract after-state (€184.61 · €42.46 · €6.07); Undo: back to €364.31 · €83.78 · €11.97', async () => {
    const api = createMockClient()
    const before = await api.overview('CUST00860', 'en')
    expect(displays(before)).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
    await api.label(request('unexpected_necessities'))
    const answered = await api.overview('CUST00860', 'en')
    expect(displays(answered)).toEqual(['€184.61 a month', '€42.46 a week', '€6.07 a day'])
    // The week and the day are the contract card's own Numbers, with their evidence, not recomputed.
    const card = examples['card.safe_to_save'] as unknown as NonNullable<OverviewResponse['safe_to_save']>
    expect(answered.safe_to_save?.weekly?.evidence_ref).toBe(card.weekly?.evidence_ref)
    expect(answered.safe_to_save?.daily?.evidence_ref).toBe(card.daily?.evidence_ref)
    // So are the parts of the month and of the stock: €783.79 − €599.18 under €184.61, not the old €963.49.
    const parts = (overview: OverviewResponse) => overview.safe_to_save?.monthly_components.map((c) => c.amount.display)
    expect(parts(answered)).toEqual(['€783.79 a month', '€599.18 a month'])
    expect(answered.safe_to_save?.stock_components).toEqual(card.stock_components)
    expect(answered.safe_to_save?.subtitle).toBe(card.subtitle)
    await api.label(request(null))
    const undone = await api.overview('CUST00860', 'en')
    expect(displays(undone)).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
    expect(parts(undone)).toEqual(['€963.49 a month', '€599.18 a month'])
  })

  it('My choice moves no safe-to-save number, so the week and the day stay', async () => {
    const api = createMockClient()
    await api.label(request('everyday_spending'))
    expect(displays(await api.overview('CUST00860', 'en'))).toEqual(['€364.31 a month', '€83.78 a week', '€11.97 a day'])
  })
})
