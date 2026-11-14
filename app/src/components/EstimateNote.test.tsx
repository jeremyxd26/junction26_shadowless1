import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Estimate, Num } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { estimateParts } from '../lib/estimate.ts'
import { EstimateNote } from './EstimateBadge.tsx'

const examples = contract.examples as unknown as Record<string, unknown>

const num = (display: string, ref: string | null, method = 'test.metric@1', label = 'A number'): Num => ({
  value: 1,
  unit: 'eur',
  period: { start: '2026-10-01', end: '2026-10-07', label: 'Next 7 days' },
  method,
  evidence_ref: ref,
  label,
  display,
})

const render = (estimate: Estimate) => renderToStaticMarkup(<EstimateNote estimate={estimate} id="note" />)

describe('the estimate note (#504, contract 0.3.6)', () => {
  // The tests run in Node: NumberChip reads a motion token while rendering.
  beforeAll(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
  })
  afterAll(() => vi.unstubAllGlobals())

  it('renders an observed Number from the estimate itself, even when no numbers map holds it', () => {
    // The forecast's daily pace appears nowhere but in its estimate (contract section 3, Estimates).
    const pace = num('€41.20 a day', 'ev_only_in_estimate', 'balance_forecast.daily_pace_eur@1', 'Daily pace')
    const numbers: Record<string, Num> = {} // the answer's map: empty, never consulted
    const html = render({ label: 'Estimate', text: 'A forecast.', observed: [pace], assumptions: [] })
    expect(Object.keys(numbers)).toHaveLength(0)
    expect(html).toContain('Based on')
    expect(html).toContain('Daily pace')
    expect(html).toContain('€41.20 a day')
    expect(html).toMatch(/<button[^>]*aria-label="Daily pace: €41.20 a day/)
  })

  it('renders a user_input@1 value as a plain chip, not a button', () => {
    const cut = num('20%', null, 'user_input@1', 'Your cut')
    const html = render({
      label: 'Estimate',
      text: 'What if.',
      observed: [],
      assumptions: [{ code: 'cut_share', text: 'You cut this spending by your share; the rest stays the same.', value: cut }],
    })
    expect(html).toContain('We assume')
    // The only chip in this note is the cut: it is a span pill, and the note has no button at all.
    expect(html).toContain('20%')
    expect(html).toMatch(/<span class="[^"]*rounded-pill[^"]*">/)
    expect(html).not.toContain('<button')
  })

  it('shows an unknown assumption code by its text only, and an older estimate as before', () => {
    const html = render({ label: 'Estimate', text: 'T.', assumptions: [{ code: 'not_a_code', text: 'Something assumed.', value: null }] })
    expect(html).toContain('Something assumed.')
    const older = render({ label: 'Estimate', text: 'Only the text.' })
    expect(older).not.toContain('Based on')
    expect(older).not.toContain('We assume')
    expect(older).toContain('Only the text.')
  })

  it('shows each Number once per note, by evidence_ref', () => {
    const goal = num('€360.00 a month', 'ev_goal', 'safe_to_spend.savings_goal_eur@1', 'Savings goal')
    const parts = estimateParts({
      label: 'Estimate',
      text: 'T.',
      observed: [num('€1.00', 'ev_a'), num('€1.00', 'ev_a'), goal],
      assumptions: [{ code: 'savings_goal_first', text: 'A goal is put aside first.', value: goal }],
    })
    expect(parts.observed.map((n) => n.evidence_ref)).toEqual(['ev_a'])
    expect(parts.assumptions[0].value?.evidence_ref).toBe('ev_goal')
  })

  it('reads the contract examples: every estimate in them renders without a crash', () => {
    const estimates: Estimate[] = []
    const walk = (value: unknown) => {
      if (Array.isArray(value)) value.forEach(walk)
      else if (typeof value === 'object' && value !== null) {
        const record = value as Record<string, unknown>
        if (Array.isArray(record.assumptions) && typeof record.text === 'string' && typeof record.label === 'string') {
          estimates.push(record as unknown as Estimate)
        }
        Object.values(record).forEach(walk)
      }
    }
    walk(examples)
    expect(estimates.length).toBeGreaterThan(3)
    for (const estimate of estimates) {
      const html = render(estimate)
      for (const assumption of estimate.assumptions ?? []) expect(html).toContain(assumption.text.replace(/&/g, '&amp;').replace(/'/g, '&#x27;'))
    }
  })
})
