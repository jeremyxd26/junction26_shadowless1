import { describe, expect, it } from 'vitest'
import { isAway } from './scrollAway.ts'

describe('the scroll-to-latest button', () => {
  it('shows only when the customer is scrolled up from the bottom of the thread', () => {
    expect(isAway(0, 800, 3000)).toBe(true)
    expect(isAway(2200, 800, 3000)).toBe(false)
    expect(isAway(2100, 800, 3000)).toBe(false)
    expect(isAway(2000, 800, 3000)).toBe(true)
  })
})
