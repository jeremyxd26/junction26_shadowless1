import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { BreakdownCard } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { BasketStrip, type BasketStripProps } from './BasketStrip.tsx'
import type { NumberMotion } from './cards.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const examples = contract.examples as unknown as Record<string, { cards: BreakdownCard[] }>
const pending = examples['overview.response_pending'].cards.find((card) => card.type === 'breakdown')!
const render = (props: Partial<BasketStripProps> = {}) => renderToStaticMarkup(<BasketStrip card={pending} {...props} />)
const count = (html: string, text: string) => html.split(text).length - 1

describe('BasketStrip', () => {
  // The tests run in Node: the chips read duration tokens, the URL and the reduced-motion setting.
  beforeAll(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterAll(() => vi.unstubAllGlobals())

  it('carries no flight target without `flight`', () => {
    const html = render()
    expect(html).not.toContain('id="baskets-title"')
    expect(html).not.toContain('data-amount-key')
    expect(html).not.toContain('data-basket-row')
  })

  it('carries the flight targets with `flight`: the heading id, one amount key and one row per cell', () => {
    const html = render({ flight: true })
    expect(count(html, 'id="baskets-title"')).toBe(1)
    expect(html).toMatch(/<h2 id="baskets-title" tabindex="-1"/)
    for (const key of ['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified']) {
      expect(count(html, `data-amount-key="${key}"`)).toBe(1)
      expect(count(html, `<li data-basket-row="${key}"`)).toBe(1)
    }
  })

  it('puts the focus target on the section when the heading is hidden (the mini row)', () => {
    const html = render({ flight: true, title: null, keys: ['unclassified', 'unexpected_necessities'] })
    expect(html).toMatch(/<section id="baskets-title" tabindex="-1" aria-label="Where your money goes in a typical month"/)
    expect(html).not.toContain('<h2')
    expect(count(html, 'data-amount-key=')).toBe(2)
  })

  it('shows the "was …" hint of a basket while the motion has one', () => {
    const before = pending.items.find((item) => item.key === 'unexpected_necessities')!.amount
    const motion: NumberMotion = {
      counts: {},
      was: { unexpected_necessities: { ...before, display: '€250.00 a month' } },
      steady: false,
      highlight: 'unexpected_necessities',
      waiting: 'keep',
    }
    expect(render({ flight: true, motion })).toContain('was €250.00 a month')
    expect(render({ flight: true })).not.toContain('>was €')
  })
})
