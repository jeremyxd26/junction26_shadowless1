// PROVISIONAL test fixture for the bill explanation's `forecast` (contract 0.3.4, #421), used by the
// bill mock until `npm run mocks:sync` brings the contract's own examples (PR #461 is not on dev yet).
// - `covered` and `outside_forecast`: copied by hand from the `bill.response` and
//   `bill.response_unknown` examples of PR #461. The synced examples replace them.
// - `tight` and `not_covered`: hand-written, no contract example exists. Their numbers are made up
//   for the demo and only follow the contract's rules (after = before - counted; shortfall =
//   counted - before; `chip` only for `not_covered`).
import type { BillForecast } from '../billTypes.ts'
import type { Num } from '../types.ts'

function eur(value: number, display: string, method: string, ref: string, label: string, date: string, dateLabel: string): Num {
  return {
    value,
    unit: 'eur',
    period: { start: date, end: date, label: dateLabel },
    method,
    evidence_ref: ref,
    label,
    display,
  }
}

const ASK_FORECAST = {
  type: 'ask' as const,
  label: 'See your balance forecast',
  prompt: 'Will my money last until payday?',
}

export const FORECASTS: Record<'covered' | 'tight' | 'not_covered' | 'outside_forecast', BillForecast> = {
  covered: {
    status: 'covered',
    before: eur(825.63, '€825.63', 'balance_forecast.balance_eur@1', 'ev_f2c4a6s8t0b2', 'Forecast balance on the due date', '2026-10-01', '1 Oct 2026'),
    already_counted: eur(780.0, '€780.00', 'balance_forecast.bills_to_date_eur@1', 'ev_f3h5o7u9s1e3', 'Already in the forecast for this bill by the due date', '2026-10-01', '1 Oct 2026'),
    counted: eur(32.4, '€32.40', 'bill.forecast_counted_eur@1', 'ev_f4k6m8p0r2t4', 'Taken from the forecast by this bill', '2026-10-01', '1 Oct 2026'),
    after: eur(793.23, '€793.23', 'bill.forecast_after_eur@1', 'ev_f5k7m9p1r3t5', 'Forecast balance after this bill', '2026-10-01', '1 Oct 2026'),
    shortfall: null,
    text: 'Your forecast balance on 1 Oct 2026 covers this bill: €793.23 would be left after it.',
    chip: null,
  },
  tight: {
    status: 'tight',
    before: eur(210.0, '€210.00', 'balance_forecast.balance_eur@1', 'ev_p1t2i3g4h5t6', 'Forecast balance on the due date', '2026-10-12', '12 Oct 2026'),
    already_counted: null,
    counted: eur(145.0, '€145.00', 'bill.forecast_counted_eur@1', 'ev_p2t3i4g5h6t7', 'Taken from the forecast by this bill', '2026-10-12', '12 Oct 2026'),
    after: eur(65.0, '€65.00', 'bill.forecast_after_eur@1', 'ev_p3t4i5g6h7t8', 'Forecast balance after this bill', '2026-10-12', '12 Oct 2026'),
    shortfall: null,
    text: 'Your forecast balance on 12 Oct 2026 covers this bill, but only €65.00 would be left after it.',
    chip: null,
  },
  not_covered: {
    status: 'not_covered',
    before: eur(96.2, '€96.20', 'balance_forecast.balance_eur@1', 'ev_p4n5c6o7v8r9', 'Forecast balance on the due date', '2026-10-12', '12 Oct 2026'),
    already_counted: null,
    counted: eur(145.0, '€145.00', 'bill.forecast_counted_eur@1', 'ev_p5n6c7o8v9r0', 'Taken from the forecast by this bill', '2026-10-12', '12 Oct 2026'),
    after: eur(-48.8, '-€48.80', 'bill.forecast_after_eur@1', 'ev_p6n7c8o9v0r1', 'Forecast balance after this bill', '2026-10-12', '12 Oct 2026'),
    shortfall: eur(48.8, '€48.80', 'bill.forecast_shortfall_eur@1', 'ev_p7n8c9o0v1r2', 'Missing on the due date', '2026-10-12', '12 Oct 2026'),
    text: 'Your forecast balance on 12 Oct 2026 is €96.20, so €48.80 is missing for this bill on that day.',
    chip: ASK_FORECAST,
  },
  outside_forecast: {
    status: 'outside_forecast',
    before: null,
    already_counted: null,
    counted: null,
    after: null,
    shortfall: null,
    text: 'Due on 20 Oct 2026, beyond your balance forecast, which runs until the day before your payday on 15 Oct 2026.',
    chip: null,
  },
}
