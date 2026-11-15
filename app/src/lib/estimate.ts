// The structured parts of an estimate (contract 0.3.6, #380, #504). The Numbers are read from the
// estimate itself, never looked up in an answer's `numbers` map (which holds only the Numbers the
// text cites). An older API without these fields gives empty lists, so the note is as before.
import type { Estimate, EstimateAssumption, Num } from '../api/types.ts'

export interface EstimateParts {
  /** "Based on": each Number once (by `evidence_ref`), minus those shown beside an assumption. */
  observed: Num[]
  /** "We assume": every assumption with a text, in order, its value as given (or null). */
  assumptions: EstimateAssumption[]
}

function isNum(value: unknown): value is Num {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Num).display === 'string' &&
    typeof (value as Num).method === 'string'
  )
}

/**
 * The estimate's observed Numbers and assumptions, de-duplicated by `evidence_ref` so no chip
 * appears twice in one note: an assumption keeps its value beside its sentence, and the same
 * Number is then left out of "Based on". Numbers without a ref (`user_input@1`) are never merged.
 */
export function estimateParts(estimate: Estimate): EstimateParts {
  const assumptions = (Array.isArray(estimate.assumptions) ? estimate.assumptions : [])
    .filter((item) => item && typeof item.text === 'string' && item.text.trim() !== '')
    .map((item) => ({ code: item.code, text: item.text, value: isNum(item.value) ? item.value : null }))
  const shown = new Set(assumptions.map((item) => item.value?.evidence_ref).filter((ref): ref is string => !!ref))
  const observed: Num[] = []
  for (const number of Array.isArray(estimate.observed) ? estimate.observed : []) {
    if (!isNum(number)) continue
    const ref = number.evidence_ref
    if (ref) {
      if (shown.has(ref)) continue
      shown.add(ref)
    }
    observed.push(number)
  }
  return { observed, assumptions }
}

/** The safe-to-spend estimate's parts by method, in receipt order: the balance, then what is set aside. */
const RECEIPT = [
  ['safe_to_spend.balance_eur@1', 'balance'],
  ['safe_to_spend.bills_due_eur@1', 'bills'],
  ['safe_to_spend.essentials_reserve_eur@1', 'essentials'],
  ['safe_to_spend.irregular_reserve_eur@1', 'reserve'],
  ['safe_to_spend.cushion_eur@1', 'cushion'],
] as const

export type ReceiptKey = (typeof RECEIPT)[number][1]

/**
 * The hero's estimate as receipt lines (Renat's phone test): each part the API gives, found by its method among the
 * observed Numbers and the assumptions' values, shown with the API's own display (no client maths). Null unless the
 * balance and at least one part set aside are there, so any other estimate keeps the full note.
 */
export function estimateReceipt(estimate: Estimate): { key: ReceiptKey; number: Num }[] | null {
  const numbers = [
    ...(Array.isArray(estimate.observed) ? estimate.observed : []),
    ...(Array.isArray(estimate.assumptions) ? estimate.assumptions.map((item) => item?.value) : []),
  ].filter(isNum)
  const lines = RECEIPT.flatMap(([method, key]) => {
    const number = numbers.find((candidate) => candidate.method === method)
    return number ? [{ key, number }] : []
  })
  return lines.length >= 2 && lines[0].key === 'balance' ? lines : null
}
