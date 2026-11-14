// PROVISIONAL test fixture for the bill explanation's `forecast` (contract 0.3.4, #421), used by the
// bill mock. The contract has examples for `covered` (`bill.response`), `outside_forecast`
// (`bill.response_unknown`) and `not_covered` (`bill.response_not_covered`); the mock uses those.
// Only `tight` has no contract example: it is hand-written here, its numbers made up for the demo,
// following the contract's rules (11.2): a bill outside the forecast's bills takes its whole
// amount, so `counted` is the bill's amount Number; `after = before - counted`; no `shortfall` and
// no `chip` (those are for `not_covered` only).
import type { BillForecast } from '../billTypes.ts'
import type { Num } from '../types.ts'

function eur(value: number, display: string, method: string, ref: string | null, label: string): Num {
  return {
    value,
    unit: 'eur',
    period: { start: '2026-10-12', end: '2026-10-12', label: '12 Oct 2026' },
    method,
    evidence_ref: ref,
    label,
    display,
  }
}

export const TIGHT_FORECAST: BillForecast = {
  status: 'tight',
  before: eur(210.0, '€210.00', 'balance_forecast.balance_eur@1', 'ev_p1t2i3g4h5t6', 'Forecast balance on the due date'),
  already_counted: null,
  // As in the contract's `not_covered` example: nothing of the bill is in the forecast yet, so it
  // takes the whole amount, the bill's own amount Number.
  counted: eur(145.0, '€145.00', 'user_input@1', null, 'Amount due'),
  after: eur(65.0, '€65.00', 'bill.forecast_after_eur@1', 'ev_p3t4i5g6h7t8', 'Forecast balance after this bill'),
  shortfall: null,
  text: 'Your forecast balance on 12 Oct 2026 covers this bill, but only €65.00 would be left after it.',
  chip: null,
}
