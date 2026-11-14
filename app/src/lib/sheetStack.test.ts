import { describe, expect, it } from 'vitest'
import { topSheet } from './sheetStack.ts'

// Sheets as their place in the document: overview 1, what-if 2, evidence 3 (App's mount order).
const after = (a: number, b: number) => a > b

describe('topSheet (#516)', () => {
  it('is the sheet that comes last in the document, whatever order they opened in', () => {
    // A deep-linked overview mounts last, once its data is there; it is still under the others.
    expect(topSheet([2, 3, 1], after)).toBe(3)
    expect(topSheet([2, 1], after)).toBe(2)
    expect(topSheet([3, 2], after)).toBe(3)
  })

  it('is the only sheet when one is open, and none when none is', () => {
    expect(topSheet([1], after)).toBe(1)
    expect(topSheet([], after)).toBeNull()
  })
})
