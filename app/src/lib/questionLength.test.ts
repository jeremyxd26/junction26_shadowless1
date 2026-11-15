import { describe, expect, it } from 'vitest'
import { chatStrings } from './chatStrings.ts'
import { NEAR_LIMIT, fitPaste } from './questionLength.ts'
import { MAX_QUESTION } from './useChat.ts'

const sentence = 'Where did my money go in September and how does it compare with August? '
const long = sentence.repeat(30) // about 2,200 characters

describe('a paste over the 500-character limit (#716)', () => {
  it('leaves a paste that fits to the browser', () => {
    expect(fitPaste('', 0, 0, 'Where did my money go?')).toBeNull()
    expect(fitPaste('a'.repeat(480), 480, 480, 'b'.repeat(20))).toBeNull()
  })

  it('cuts a long paste to at most 500 characters, at a word break, with the caret after it', () => {
    const fitted = fitPaste('', 0, 0, long)!
    expect(fitted.value.length).toBeLessThanOrEqual(MAX_QUESTION)
    expect(fitted.value.length).toBeGreaterThan(MAX_QUESTION - 40)
    // It ends on a whole word of the pasted text.
    expect(long.startsWith(fitted.value)).toBe(true)
    expect(long[fitted.value.length]).toMatch(/\s/)
    expect(fitted.caret).toBe(fitted.value.length)
  })

  it('cuts a word with no break near the limit where the limit is', () => {
    const fitted = fitPaste('', 0, 0, 'a'.repeat(900))!
    expect(fitted.value).toBe('a'.repeat(MAX_QUESTION))
  })

  it('pastes over the selection, keeps the text around it, and turns line breaks into spaces', () => {
    const current = 'Total of: X please'
    const start = current.indexOf('X')
    const fitted = fitPaste(current, start, start + 1, '1. 120,50\n2. 89,90\n' + '9 '.repeat(300), 60)!
    expect(fitted.value.startsWith('Total of: 1. 120,50 2. 89,90 9 9')).toBe(true)
    expect(fitted.value.endsWith(' please')).toBe(true)
    expect(fitted.value.length).toBeLessThanOrEqual(60)
    expect(fitted.value.slice(0, fitted.caret).endsWith('9')).toBe(true)
  })

  it('says how much is left near the limit and that a paste was cut, in EN and FI', () => {
    expect(NEAR_LIMIT).toBe(50)
    expect(chatStrings('en').charactersLeft(12)).toBe('12 characters left')
    expect(chatStrings('en').charactersLeft(1)).toBe('1 character left')
    expect(chatStrings('fi').charactersLeft(12)).toBe('12 merkkiä jäljellä')
    expect(chatStrings('en').cut).toMatch(/500/)
    expect(chatStrings('fi').cut).toMatch(/500/)
  })
})
