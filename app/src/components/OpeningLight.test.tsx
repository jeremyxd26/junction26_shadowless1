// The opening's light look (Renat's redesign, #843): the hero as a centred key line, "Sentti asks" as a bubble.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { MetricCard, ReviewCard as ReviewCardData } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
import { HeroSummary } from './cards.tsx'
import { ReviewAnswered, ReviewAsking } from './ReviewCard.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

// The motion tokens are read from CSS; on the server there is none.
vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
vi.stubGlobal('document', { documentElement: {} })
vi.stubGlobal('window', {
  matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
  addEventListener: () => {},
  removeEventListener: () => {},
  location: { search: '', pathname: '/', href: 'http://localhost/' },
})

const examples = contract.examples as unknown as Record<string, unknown>
const overview = examples['overview.response'] as { hero: MetricCard }
const review = examples['card.review'] as ReviewCardData

function render(node: ReturnType<typeof createElement>, lang: 'en' | 'fi' = 'en') {
  return renderToStaticMarkup(createElement(SettingsContext, { value: { lang, customerId: 'CUST00860', t: strings(lang) } }, node))
}

describe('the light opening (#843)', () => {
  it('the hero is a centred key line: no card colour, the amount first in its button, the caption, the estimate', () => {
    const html = render(createElement(HeroSummary, { card: overview.hero }))
    expect(html).toMatch(/^<section data-opening-part="hero" class="[^"]*text-center/)
    expect(html).not.toContain('bg-hero')
    // What the demo check reads: the first span inside the hero's button is the amount.
    expect(html).toMatch(new RegExp(`<button[^>]*><span[^>]*font-light[^>]*>${overview.hero.primary.display.replace(/[.$]/g, '\\$&')}</span></button>`))
    expect(html).toContain('left to spend this week')
    // The "was …" line keeps its room before any answer, so the count never moves the layout.
    expect(html).toContain('invisible')
  })

  it('"Sentti asks" is a bubble: hidden heading, "Quick question:", the API answers as outlined pills, Not sure and why', () => {
    const html = render(
      createElement(ReviewAsking, { card: review, busy: null, error: null, onAnswer: () => {}, onNotSure: () => {}, onRetry: () => {}, leaving: false, bubble: true }),
    )
    expect(html).toContain('data-opening-part="review"')
    expect(html).toContain('<h2 id=')
    expect(html).toMatch(/class="sr-only">Sentti asks<\/h2>/)
    expect(html).toContain('Quick question:')
    expect(html).not.toContain('bg-deep')
    for (const option of review.options) expect(html).toContain(`>${option.label.en}</span>`)
    expect(html.match(/rounded-pill border-\[1\.5px\] border-brand/g)).toHaveLength(review.options.length)
    expect(html).toContain('>Not sure</button>')
    expect(html).toContain('aria-label="Why Sentti asks"')
    const fi = render(
      createElement(ReviewAsking, { card: review, busy: null, error: null, onAnswer: () => {}, onNotSure: () => {}, onRetry: () => {}, leaving: false, bubble: true }),
      'fi',
    )
    expect(fi).toContain('Pikakysymys:')
    expect(fi).toMatch(/class="sr-only">Sentti kysyy<\/h2>/)
  })

  it('after the answer the bubble shows the choice and an Undo named exactly "Undo"', () => {
    const html = render(createElement(ReviewAnswered, { card: review, basket: review.options[0].basket, onUndo: () => {}, bubble: true }))
    expect(html).toContain('data-opening-part="review"')
    expect(html).toContain(`${review.options[0].label.en}</p>`)
    expect(html).toMatch(/>Undo<\/button>/)
  })
})
