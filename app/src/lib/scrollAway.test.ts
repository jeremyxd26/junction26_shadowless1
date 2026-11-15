import { describe, expect, it } from 'vitest'
import { ABOVE_COMPOSER_GAP, buttonLift, isAway } from './scrollAway.ts'

describe('the scroll-to-latest button', () => {
  it('shows only when the customer is scrolled up from the bottom of the thread', () => {
    expect(isAway(0, 800, 3000)).toBe(true)
    expect(isAway(2200, 800, 3000)).toBe(false)
    expect(isAway(2100, 800, 3000)).toBe(false)
    expect(isAway(2000, 800, 3000)).toBe(true)
  })
})

describe('the scroll-to-latest button sits on the composer (#762)', () => {
  const inside = { top: 760, bottom: 790, height: 30 }
  it('keeps the old 84 px above a 73 px composer at normal text', () => {
    expect(buttonLift(812, 812 - 73, [inside])).toBe(84)
  })
  it('follows a taller composer: 200 % text or the length note', () => {
    expect(buttonLift(812, 812 - 133, [])).toBe(133 + ABOVE_COMPOSER_GAP)
    expect(buttonLift(812, 812 - 105, [])).toBe(105 + ABOVE_COMPOSER_GAP)
  })
  it('goes above a line the composer shows over itself (the mic status), and ignores what is inside', () => {
    const micLine = { top: 690, bottom: 731, height: 41 }
    expect(buttonLift(812, 739, [inside, micLine])).toBe(812 - 690 + ABOVE_COMPOSER_GAP)
    // A 1 px screen-reader-only element is not a line.
    expect(buttonLift(812, 739, [{ top: 700, bottom: 701, height: 1 }])).toBe(84)
  })
})
