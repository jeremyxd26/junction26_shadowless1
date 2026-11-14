import { afterEach, describe, expect, it, vi } from 'vitest'
import { headerBottom, landBelowHeader, landingTop } from './threadScroll.ts'

describe('landing below the measured header (#332)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const stub = (bottom: number | null) => {
    const scrollTo = vi.fn()
    vi.stubGlobal('document', { querySelector: () => (bottom === null ? null : { getBoundingClientRect: () => ({ bottom }) }) })
    vi.stubGlobal('window', { scrollY: 1000, scrollTo })
    return scrollTo
  }

  it('keeps the 64 px of normal text and clears the taller header of 200 % text', () => {
    stub(52)
    expect(landingTop()).toBe(64)
    stub(176)
    expect(landingTop()).toBe(188)
  })

  it('scrolls so the element starts just below the header', () => {
    const scrollTo = stub(176)
    landBelowHeader({ getBoundingClientRect: () => ({ top: 500 }) } as unknown as Element, false)
    expect(scrollTo).toHaveBeenCalledWith({ top: 1000 + 500 - 188, behavior: 'auto' })
  })

  it('treats a page without a header as a header of 0 px', () => {
    stub(null)
    expect(headerBottom()).toBe(0)
  })
})
