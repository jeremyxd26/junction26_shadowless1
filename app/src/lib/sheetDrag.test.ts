import { describe, expect, it } from 'vitest'
import { DISMISS_SHARE, FLICK_PX_PER_MS, rubberBand, scrolledDown, shouldDismiss } from './sheetDrag.ts'

describe('dragging a bottom sheet down', () => {
  it('follows the finger 1:1 downward and resists upward, never more than 40 px', () => {
    expect(rubberBand(0)).toBe(0)
    expect(rubberBand(120)).toBe(120)
    expect(rubberBand(-20)).toBeLessThan(0)
    expect(rubberBand(-20)).toBeGreaterThan(-20)
    expect(rubberBand(-10_000)).toBeGreaterThan(-40)
  })

  it('closes past 30 % of the height or on a fast flick down, and springs back otherwise', () => {
    expect(DISMISS_SHARE).toBe(0.3)
    expect(FLICK_PX_PER_MS).toBe(0.5)
    expect(shouldDismiss(181, 600, 0.1)).toBe(true) // past 30 % of 600 px
    expect(shouldDismiss(150, 600, 0.1)).toBe(false) // a slow, short drag springs back
    expect(shouldDismiss(40, 600, 0.9)).toBe(true) // a flick
    expect(shouldDismiss(-30, 600, 0.9)).toBe(false) // up is never a close
    expect(shouldDismiss(0, 600, 0)).toBe(false)
  })

  it('starts no drag in content scrolled away from its top', () => {
    // The tests run without a DOM: the three nodes as far as the check reads them.
    const page = { scrollTop: 0, parentElement: null }
    const panel = { scrollTop: 0, parentElement: page }
    const content = { scrollTop: 0, parentElement: panel }
    const row = { scrollTop: 0, parentElement: content }
    const check = () => scrolledDown(row as unknown as Element, panel as unknown as Element)
    expect(check()).toBe(false)
    content.scrollTop = 120
    expect(check()).toBe(true)
    content.scrollTop = 0
    panel.scrollTop = 8 // a short sheet scrolls as a whole
    expect(check()).toBe(true)
    panel.scrollTop = 0
    page.scrollTop = 300 // what lies outside the sheet does not count
    expect(check()).toBe(false)
  })
})
