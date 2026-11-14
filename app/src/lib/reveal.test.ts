import { describe, expect, it } from 'vitest'
import { REVEAL_MAX_MS, REVEAL_TICK_MS, firstWords, holdsCards, remainingMs, revealStep, wordEnds, wordsToShow } from './reveal.ts'

const TEXT = 'You can spend {{n1}} this week. That keeps {{n2}} for bills.'

describe('the typing reveal (#686)', () => {
  it('cuts a text only at the end of a word, so a number token is never split', () => {
    expect(wordEnds(TEXT)).toHaveLength(11)
    expect(firstWords(TEXT, 4)).toBe('You can spend {{n1}}')
    expect(firstWords(TEXT, 0)).toBe('')
    expect(firstWords(TEXT, 99)).toBe(TEXT)
    expect(firstWords(TEXT, Number.POSITIVE_INFINITY)).toBe(TEXT)
  })

  it('reveals any text in at most one second', () => {
    for (const total of [1, 5, 33, 60, 200, 1000]) {
      const steps = Math.ceil(total / revealStep(total))
      expect(steps * REVEAL_TICK_MS).toBeLessThanOrEqual(REVEAL_MAX_MS + REVEAL_TICK_MS)
    }
    expect(revealStep(5)).toBe(1)
  })

  it('animates nothing with reduced motion', () => {
    expect(wordsToShow(0, { live: true, reduced: true, skipped: false })).toBe(Number.POSITIVE_INFINITY)
  })

  it('shows everything at once after a tap', () => {
    expect(wordsToShow(2, { live: true, reduced: false, skipped: true })).toBe(Number.POSITIVE_INFINITY)
  })

  it('never animates an answer from history', () => {
    expect(wordsToShow(0, { live: false, reduced: false, skipped: false })).toBe(Number.POSITIVE_INFINITY)
  })

  it('reveals a live answer word by word', () => {
    expect(wordsToShow(3, { live: true, reduced: false, skipped: false })).toBe(3)
  })

  it('lets a card wait for the rest of the text, and not at all once it is shown', () => {
    expect(remainingMs(0, 10)).toBe(10 * REVEAL_TICK_MS)
    expect(remainingMs(10, 10)).toBe(0)
    expect(remainingMs(Number.POSITIVE_INFINITY, 10)).toBe(0)
  })

  it('keeps a live answer\'s cards behind the skeleton while it streams and while its text types in', () => {
    expect(holdsCards(0, { streaming: true, revealing: false })).toBe(true)
    expect(holdsCards(4, { streaming: false, revealing: true })).toBe(true)
    expect(holdsCards(10, { streaming: false, revealing: false })).toBe(false)
  })

  it('never holds the cards when the reveal is off (history, reduced motion, a tap)', () => {
    expect(holdsCards(Number.POSITIVE_INFINITY, { streaming: true, revealing: false })).toBe(false)
  })
})
