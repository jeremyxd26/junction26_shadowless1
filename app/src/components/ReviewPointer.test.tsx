import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Card, ReviewCard } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { OpeningContext, type Opening, type ShownReview } from '../lib/openingContext.ts'
import { reviewPlacement, threadReview, THREAD_REVIEW_START } from '../lib/reviewPointer.ts'
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
const TX = review.tx_ref

function opening(shownReview: ShownReview | null, threadReviews: Record<string, string> = {}): Opening {
  return {
    reviewTxRef: TX,
    shownReview,
    reportReview: vi.fn(),
    threadReviews,
    claimThreadReview: vi.fn(),
    releaseThreadReview: vi.fn(),
    refresh: vi.fn(),
    scrollToReview: vi.fn(),
  }
}

const render = (value: Opening | null) =>
  renderToStaticMarkup(
    <OpeningContext.Provider value={value}>
      <AnswerCard card={review as unknown as Card} />
    </OpeningContext.Provider>,
  )

describe('reviewPlacement (#450)', () => {
  it('points only when the opening shows this purchase (asking or answered) or another turn shows it', () => {
    expect(reviewPlacement(TX, 'me', opening({ txRef: TX, phase: 'asking' }))).toBe('pointer')
    expect(reviewPlacement(TX, 'me', opening({ txRef: TX, phase: 'answered' }))).toBe('pointer')
    expect(reviewPlacement(TX, 'me', opening(null, { [TX]: 'earlier-turn' }))).toBe('pointer')
  })

  it('shows the card itself after Not sure, for another purchase, with no question, or outside the thread', () => {
    expect(reviewPlacement(TX, 'me', opening(null))).toBe('card') // Not sure, or no question in the opening
    expect(reviewPlacement(TX, 'me', opening({ txRef: 'txr_other', phase: 'asking' }))).toBe('card')
    expect(reviewPlacement(TX, 'me', opening(null, { [TX]: 'me' }))).toBe('card') // this turn holds it
    expect(reviewPlacement(TX, 'me', null)).toBe('card')
  })
})

describe('threadReview: the review card answered in the thread', () => {
  const error = { message: 'Try again.', retryable: true, until: null }

  it('sends one answer at a time, then shows it answered', () => {
    const sending = threadReview(THREAD_REVIEW_START, { type: 'send', basket: 'unexpected_necessities' })
    expect(sending).toEqual({ kind: 'asking', busy: 'unexpected_necessities', error: null })
    expect(threadReview(sending, { type: 'send', basket: 'everyday_spending' })).toBe(sending)
    expect(threadReview(sending, { type: 'saved', basket: 'unexpected_necessities' })).toEqual({ kind: 'answered', basket: 'unexpected_necessities' })
  })

  it('keeps the question with the error after a failed save, and closes it when the review is gone', () => {
    const sending = threadReview(THREAD_REVIEW_START, { type: 'send', basket: 'everyday_spending' })
    expect(threadReview(sending, { type: 'failed', error })).toEqual({ kind: 'asking', busy: null, error })
    expect(threadReview(sending, { type: 'gone' })).toEqual({ kind: 'not_sure' })
  })

  it('Not sure closes the card, but not while an answer is being sent', () => {
    expect(threadReview(THREAD_REVIEW_START, { type: 'not_sure' })).toEqual({ kind: 'not_sure' })
    const sending = threadReview(THREAD_REVIEW_START, { type: 'send', basket: 'everyday_spending' })
    expect(threadReview(sending, { type: 'not_sure' })).toBe(sending)
  })
})

describe('a review card in an answer (#318, #450)', () => {
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
  const answers = review.options.map((option) => `>${option.label.en}<`)

  it('when the opening shows the question: only the line and a 44 px "Show", no second question', () => {
    const html = render(opening({ txRef: TX, phase: 'asking' }))
    expect(html).toContain(s.asked)
    expect(html).toMatch(new RegExp(`<button type="button" aria-label="${s.showLabel}" class="inline-flex min-h-11[^"]*">${s.show}</button>`))
    for (const label of answers) expect(html).not.toContain(label)
    expect(html).not.toContain('data-review-card')
  })

  it('when nobody shows it (Not sure): the review card itself with its answer buttons, and no pointer', () => {
    const html = render(opening(null))
    expect(html).toContain(`data-review-card="${TX}"`)
    for (const label of answers) expect(html).toContain(label)
    expect(html).not.toContain(s.asked)
    expect(html).not.toContain(`>${s.show}<`)
  })

  it('outside the thread (no opening) the card itself shows too', () => {
    const html = render(null)
    expect(html).toContain(`data-review-card="${TX}"`)
    expect(html).not.toContain(s.asked)
  })

  it('never says the question was answered in the pointer', () => {
    for (const shown of [{ txRef: TX, phase: 'asking' as const }, { txRef: TX, phase: 'answered' as const }]) {
      expect(render(opening(shown)).toLowerCase()).not.toContain('answered')
    }
  })
})
