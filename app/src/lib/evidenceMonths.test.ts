import { describe, expect, it } from 'vitest'
import type { EvidenceRow } from '../api/types.ts'
import { monthsBetween, rowsByMonth } from './evidenceMonths.ts'

const row = (id: string, date: string): EvidenceRow => ({
  tx_id: id, date, time: '12:00', category: 'Restaurants', merchant: null, mcc: null, amount: '-1.00', currency: 'EUR',
  display: '-€1.00',
})

describe('the evidence list by month', () => {
  it('counts the calendar months a period touches', () => {
    expect(monthsBetween('2026-04-01', '2026-09-30')).toBe(6)
    expect(monthsBetween('2026-09-01', '2026-09-30')).toBe(1)
    expect(monthsBetween('2025-11-01', '2026-02-28')).toBe(4)
  })

  it('keeps the rows newest first and groups them under their month', () => {
    const groups = rowsByMonth([row('a', '2026-09-28'), row('b', '2026-09-02'), row('c', '2026-08-30'), row('d', '2026-04-03')])
    expect(groups.map((g) => [g.month, g.rows.map((r) => r.tx_id)])).toEqual([
      ['2026-09', ['a', 'b']], ['2026-08', ['c']], ['2026-04', ['d']],
    ])
  })
})
