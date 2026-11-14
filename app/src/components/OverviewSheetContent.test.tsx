import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { OverviewResponse } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { OverviewSheetContent } from './OverviewSheetContent.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const examples = contract.examples as unknown as Record<string, OverviewResponse>
const render = (name: string) => renderToStaticMarkup(<OverviewSheetContent overview={examples[name]} />)

describe('OverviewSheetContent', () => {
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

  it('shows the hero, baskets, bills, safe to save and the what-if entry, in that order (Sanna)', () => {
    const html = render('overview.response_pending')
    const sanna = examples['overview.response_pending']
    const at = (text: string) => {
      const index = html.indexOf(text)
      expect(index, text).toBeGreaterThanOrEqual(0)
      return index
    }
    const hero = at(sanna.hero!.primary.display)
    const baskets = at('Where your money goes in a typical month')
    const safeToSave = at(sanna.safe_to_save!.title)
    const whatIf = at('What if I spent 20% less on restaurants?')
    expect(hero).toBeLessThan(baskets)
    expect(baskets).toBeLessThan(safeToSave)
    expect(safeToSave).toBeLessThan(whatIf)
  })

  it('never carries the flight targets or a review card', () => {
    for (const name of ['overview.response_pending', 'overview.response', 'overview.response_no_hero']) {
      const html = render(name)
      expect(html).not.toContain('id="baskets-title"')
      expect(html).not.toContain('data-amount-key')
      expect(html).not.toContain(examples['overview.response_pending'].reviews[0].question.en.slice(0, 20))
    }
  })

  it('shows the insights when there are some (Aino)', () => {
    const aino = examples['overview.response']
    const html = render('overview.response')
    for (const insight of aino.insights) expect(html).toContain(insight.title)
  })

  it('leaves the hero out with no placeholder when hero is null', () => {
    const html = render('overview.response_no_hero')
    const withHero = render('overview.response')
    const heroTitle = examples['overview.response'].hero!.title
    expect(withHero).toContain(heroTitle)
    expect(html).not.toContain(heroTitle)
    expect(html).not.toContain('bg-hero')
  })
})
