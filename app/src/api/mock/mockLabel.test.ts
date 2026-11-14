import { describe, expect, it } from 'vitest'
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
