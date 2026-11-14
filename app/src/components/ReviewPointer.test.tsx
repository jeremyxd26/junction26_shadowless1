import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Card, ReviewCard } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { OpeningContext, type Opening } from '../lib/openingContext.ts'
import { pointerState } from '../lib/reviewPointer.ts'
import { reviewStrings } from '../lib/reviewStrings.ts'
import { AnswerCard } from './AnswerCard.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const review = contract.examples['card.review'] as unknown as ReviewCard
const opening = (reviewTxRef: string | null): Opening => ({ reviewTxRef, refresh: vi.fn(), scrollToReview: vi.fn() })
const render = (value: Opening | null) =>
  renderToStaticMarkup(
    <OpeningContext.Provider value={value}>
      <AnswerCard card={review as unknown as Card} />
    </OpeningContext.Provider>,
  )

describe('pointerState', () => {
  it('asks when the opening asks about the same purchase, else points elsewhere, and is plain outside the thread', () => {
    expect(pointerState(review.tx_ref, opening(review.tx_ref))).toBe('asking')
    expect(pointerState(review.tx_ref, opening('txr_other'))).toBe('elsewhere')
    expect(pointerState(review.tx_ref, opening(null))).toBe('elsewhere')
    expect(pointerState(review.tx_ref, null)).toBe('outside')
  })
})

describe('a review card in an answer (#318)', () => {
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

  const s = reviewStrings('en')

  it('never shows a second question or its answer buttons', () => {
    for (const html of [render(opening(review.tx_ref)), render(null), render(opening('txr_other'))]) {
      expect(html).not.toContain(review.question.en)
      for (const option of review.options) expect(html).not.toContain(`>${option.label.en}<`)
      expect(html).toContain(s.asked)
    }
  })

  it('points to the opening with a 44 px "Show" button when the opening asks about it', () => {
    const html = render(opening(review.tx_ref))
    expect(html).toMatch(new RegExp(`<button type="button" aria-label="${s.showLabel}" class="inline-flex min-h-11[^"]*">${s.show}</button>`))
  })

  it('has no button outside the thread, or while the opening does not ask about it', () => {
    expect(render(null)).not.toContain('<button')
    expect(render(opening('txr_other'))).not.toContain('<button')
  })

  it('says nothing about the question being answered', () => {
    for (const html of [render(opening(review.tx_ref)), render(opening('txr_other')), render(null)]) {
      expect(html.toLowerCase()).not.toContain('answered')
    }
  })

  it('keeps every text within the length rule (title ≤ 4 words, caption ≤ 8)', () => {
    for (const lang of ['en', 'fi'] as const) {
      const t = reviewStrings(lang)
      expect(t.show.split(/\s+/).length).toBeLessThanOrEqual(4)
      expect(t.asked.split(/\s+/).length).toBeLessThanOrEqual(8)
    }
  })
})
