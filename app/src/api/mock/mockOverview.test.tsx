import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Language, OverviewResponse, ReviewCard } from '../types.ts'
import { ReviewAsking } from '../../components/ReviewCard.tsx'
import { strings } from '../../lib/i18n.ts'
import { SettingsContext } from '../../lib/settings.ts'
import contract from './contract-examples.json'
import { createMockClient } from './mockClient.ts'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const pending = contract.examples['overview.response_pending'] as unknown as OverviewResponse
const SANNA = 'CUST00860'

/** The opening's "Sentti asks" card for `review`, rendered in `lang`, as text without tags. */
function questionText(review: ReviewCard, lang: Language): string {
  const html = renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: SANNA, t: strings(lang) }}>
      <ReviewAsking card={review} busy={null} error={null} leaving={false} onAnswer={() => {}} onNotSure={() => {}} onRetry={() => {}} />
    </SettingsContext.Provider>,
  )
  return html.replace(/<[^>]*>/g, '')
}

const count = (text: string, part: string) => text.split(part).length - 1

describe('mock overview: the review amount in the request language (#463)', () => {
  beforeAll(() => {
    // The tests run in Node: the chips read duration tokens, the URL and the reduced-motion setting.
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

  it('FI: the amount is "1 080,42 €", as the Finnish question writes it; EN keeps "€1,080.42"', async () => {
    const api = createMockClient()
    const fi = (await api.overview(SANNA, 'fi')).reviews[0]
    const en = (await api.overview(SANNA, 'en')).reviews[0]
    expect(fi.amount.display).toBe('1 080,42 €')
    expect(fi.question.fi.startsWith(fi.amount.display)).toBe(true)
    expect(fi.amount.value).toBe(en.amount.value)
    expect(en.amount.display).toBe('€1,080.42')
    expect(en.question.en.startsWith(en.amount.display)).toBe(true)
  })

  it('FI opening: "Sentti asks" shows the amount exactly once, as its chip', async () => {
    const fi = (await createMockClient().overview(SANNA, 'fi')).reviews[0]
    const text = questionText(fi, 'fi')
    expect(count(text, '1 080,42 €')).toBe(1)
    expect(count(text, '€1,080.42')).toBe(0)
    // The contract example's English display with the Finnish question: the amount twice (the bug).
    const before = questionText(pending.reviews[0], 'fi')
    expect(count(before, '1 080,42 €') + count(before, '€1,080.42')).toBe(2)
  })

  it('EN opening: the amount once, as before', async () => {
    const en = (await createMockClient().overview(SANNA, 'en')).reviews[0]
    expect(count(questionText(en, 'en'), '€1,080.42')).toBe(1)
  })
})
