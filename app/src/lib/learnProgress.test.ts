import { afterEach, describe, expect, it, vi } from 'vitest'
import { markDone, parseProgress, readProgress, resetProgress, saveScore } from './learnProgress.ts'

describe('learning progress in the browser (Learn tab)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps only lesson ids, scores and the last lesson; anything else is dropped', () => {
    const raw = JSON.stringify({ done: ['money-1', 'money-1', 7, 'x'.repeat(41)], scores: { bills: 2, bad: 'a', big: 99 }, last: 'money-1', amount: '€138.79' })
    expect(parseProgress(raw)).toEqual({ done: ['money-1'], scores: { bills: 2 }, last: 'money-1' })
    expect(parseProgress('not json')).toEqual({ done: [], scores: {}, last: null })
    expect(parseProgress(null)).toEqual({ done: [], scores: {}, last: null })
  })

  it('works without storage (every access throws) and keeps one key per persona', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
      removeItem: () => {
        throw new Error('blocked')
      },
    }
    vi.stubGlobal('window', { localStorage: blocked })
    markDone('CUST-A', 'money-1')
    saveScore('CUST-A', 'money', 2)
    expect(readProgress('CUST-A')).toEqual({ done: ['money-1'], scores: { money: 2 }, last: 'money-1' })
    expect(readProgress('CUST-B').done).toEqual([])
    resetProgress('CUST-A')
    expect(readProgress('CUST-A').done).toEqual([])
  })

  it('writes the persona key with nothing but the progress', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
      },
    })
    markDone('CUST-C', 'money-2')
    expect(JSON.parse(store.get('sentti.learn.CUST-C') ?? '{}')).toEqual({ done: ['money-2'], scores: {}, last: 'money-2' })
    resetProgress('CUST-C')
    expect(store.has('sentti.learn.CUST-C')).toBe(false)
  })
})
