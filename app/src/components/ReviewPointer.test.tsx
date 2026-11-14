import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Card, Language, ReviewCard } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { BASKETS } from '../lib/baskets.ts'
import { strings } from '../lib/i18n.ts'
import { OpeningContext, type Opening, type ShownReview } from '../lib/openingContext.ts'
import { reviewPlacement, threadReview, THREAD_REVIEW_START } from '../lib/reviewPointer.ts'
import { reviewStrings } from '../lib/reviewStrings.ts'
import { SettingsContext } from '../lib/settings.ts'
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

/** The opening's question answered with Needed, as the label response names it (#452). */
const NEEDED: ShownReview = { txRef: TX, phase: 'answered', basketKey: 'unexpected_necessities', basketLabel: 'Unexpected necessities' }
const NEEDED_FI: ShownReview = { ...NEEDED, basketLabel: 'Välttämättömät' }

function opening(shownReview: ShownReview | null, threadReviews: Record<string, string> = {}): Opening {
  return {
    reviewTxRef: TX,
    shownReview,
    reportReview: vi.fn(),
    // As OpeningProvider derives it from the reported card.
    answered:
      shownReview?.phase === 'answered'
        ? { txRef: shownReview.txRef, basketKey: shownReview.basketKey, basketLabel: shownReview.basketLabel }
        : null,
    threadReviews,
    claimThreadReview: vi.fn(),
    releaseThreadReview: vi.fn(),
    refresh: vi.fn(),
    scrollToReview: vi.fn(),
  }
}

const render = (value: Opening | null, lang: Language = 'en') =>
  renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: 'CUST00860', t: strings(lang) }}>
      <OpeningContext.Provider value={value}>
        <AnswerCard card={review as unknown as Card} />
      </OpeningContext.Provider>
    </SettingsContext.Provider>,
  )

describe('reviewPlacement (#450)', () => {
  it('points only when the opening asks about this purchase or another turn shows it', () => {
    expect(reviewPlacement(TX, 'me', opening({ txRef: TX, phase: 'asking' }))).toBe('pointer')
    expect(reviewPlacement(TX, 'me', opening(null, { [TX]: 'earlier-turn' }))).toBe('pointer')
  })

  it('says where the purchase went once the opening answered it, and points again after Undo (#452)', () => {
    expect(reviewPlacement(TX, 'me', opening(NEEDED))).toBe('answered')
    expect(reviewPlacement(TX, 'me', opening(NEEDED, { [TX]: 'earlier-turn' }))).toBe('answered')
    // Undo: the opening asks again.
    expect(reviewPlacement(TX, 'me', opening({ txRef: TX, phase: 'asking' }))).toBe('pointer')
    // Another purchase answered in the opening changes nothing here.
    expect(reviewPlacement(TX, 'me', opening({ ...NEEDED, txRef: 'txr_other' }))).toBe('card')
    // An answer that closed its own card stays empty.
    expect(reviewPlacement(TX, 'me', opening(NEEDED), true)).toBe('none')
  })

  it('shows the card itself after Not sure, for another purchase, with no question, or outside the thread', () => {
    expect(reviewPlacement(TX, 'me', opening(null))).toBe('card') // Not sure, or no question in the opening
    expect(reviewPlacement(TX, 'me', opening({ txRef: 'txr_other', phase: 'asking' }))).toBe('card')
    expect(reviewPlacement(TX, 'me', opening(null, { [TX]: 'me' }))).toBe('card') // this turn holds it
    expect(reviewPlacement(TX, 'me', null)).toBe('card')
  })

  it('an answer that closed its own card (Not sure or gone) shows nothing, never a pointer to a later card', () => {
    const closed = threadReview(THREAD_REVIEW_START, { type: 'not_sure' }).kind === 'not_sure'
    const gone = threadReview(THREAD_REVIEW_START, { type: 'gone' }).kind === 'not_sure'
    expect(closed && gone).toBe(true)
    // Its card released the purchase, so a later answer shows the card and holds it.
    expect(reviewPlacement(TX, 'me', opening(null, { [TX]: 'later-turn' }), closed)).toBe('none')
    expect(reviewPlacement(TX, 'me', opening({ txRef: TX, phase: 'asking' }), closed)).toBe('none')
    expect(reviewPlacement(TX, 'me', opening(null), closed)).toBe('none')
    expect(reviewPlacement(TX, 'me', null, closed)).toBe('none')
    // The later answer itself is not closed: it shows the card.
    expect(reviewPlacement(TX, 'later-turn', opening(null, { [TX]: 'later-turn' }))).toBe('card')
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
    expect(render(opening({ txRef: TX, phase: 'asking' })).toLowerCase()).not.toContain('answered')
  })
})

describe('the answered line (#452)', () => {
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

  const icon = BASKETS.unexpected_necessities.icon

  it('EN: "You put this in <icon> <label>." with the label from the API, and no button', () => {
    const html = render(opening(NEEDED))
    expect(html).toContain(`data-review-answered="${TX}"`)
    expect(html).toContain(`You put this in <span aria-hidden="true">${icon}</span> Unexpected necessities.`)
    expect(html).not.toContain('<button')
    expect(html).not.toContain(reviewStrings('en').asked)
    expect(html).not.toContain('data-review-card')
  })

  it('FI: "Laitoit tämän koriin <icon> <label>."', () => {
    const html = render(opening(NEEDED_FI), 'fi')
    expect(html).toContain(`Laitoit tämän koriin <span aria-hidden="true">${icon}</span> Välttämättömät.`)
    expect(html).not.toContain('<button')
  })

  it('after Undo: back to "Sentti already asked…" with the 44 px Show, EN and FI', () => {
    for (const lang of ['en', 'fi'] as const) {
      const s = reviewStrings(lang)
      const html = render(opening({ txRef: TX, phase: 'asking' }), lang)
      expect(html).toContain(s.asked)
      expect(html).toMatch(new RegExp(`<button type="button" aria-label="${s.showLabel}" class="inline-flex min-h-11[^"]*">${s.show}</button>`))
      expect(html).not.toContain(s.putIn)
    }
  })
})
