import { describe, expect, it } from 'vitest'
import type { BreakdownCard } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { stripItems } from './basketStrip.ts'

const examples = contract.examples as unknown as Record<string, { cards: BreakdownCard[] }>
const pending = examples['overview.response_pending'].cards.find((card) => card.type === 'breakdown')!
const settled: BreakdownCard = {
  ...pending,
  items: pending.items.map((item) =>
    item.key === 'unclassified' ? { ...item, amount: { ...item.amount, value: 0, display: '€0.00 a month' } } : item,
  ),
}
const keysOf = (items: BreakdownCard['items']) => items.map((item) => item.key)

describe('stripItems', () => {
  it('shows the three baskets and the waiting cell while a review is pending, in the card order', () => {
    expect(keysOf(stripItems(pending))).toEqual(['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified'])
  })

  it('leaves the waiting cell out when nothing waits', () => {
    expect(keysOf(stripItems(settled))).toEqual(['regular_essentials', 'unexpected_necessities', 'everyday_spending'])
  })

  it('keeps the waiting cell while it counts to zero or fades out after an answer', () => {
    expect(keysOf(stripItems(settled, { waiting: 'keep' }))).toContain('unclassified')
    expect(keysOf(stripItems(settled, { waiting: 'leave' }))).toContain('unclassified')
  })

  it('shows only the given keys, in the card order (the mini row of a review answer)', () => {
    expect(keysOf(stripItems(pending, { keys: ['unexpected_necessities', 'unclassified'] }))).toEqual([
      'unexpected_necessities',
      'unclassified',
    ])
  })

  it('never shows an item that is not a basket', () => {
    const withOther: BreakdownCard = { ...pending, items: [...pending.items, { ...pending.items[0], key: 'other' }] }
    expect(keysOf(stripItems(withOther))).not.toContain('other')
  })
})
