// Voice mode's pure parts (#811): when a listening round ends, which answer it follows, the wave's bars.
import { describe, expect, it } from 'vitest'
import { EMPTY_ANSWER, type Answer } from './answer.ts'
import type { Turn } from './thread.ts'
import { LISTEN_MS, ONSET_MS, SILENCE_MS, endpointer, followAnswer, waveBars } from './voiceMode.ts'

/** Feeds `level` every 50 ms from `from` to `to` (ms) and returns the last state. */
function feed(ends: ReturnType<typeof endpointer>, level: number, from: number, to: number) {
  let state = ends.push(level, from)
  for (let now = from + 50; now <= to; now += 50) state = ends.push(level, now)
  return state
}

describe('endpointer (#811)', () => {
  it('waits in silence, hears speech after the onset time, and ends 1.2 s after it stops', () => {
    const ends = endpointer(0)
    expect(feed(ends, 0.01, 0, 1000)).toBe('waiting')
    expect(feed(ends, 0.5, 1050, 1050 + ONSET_MS - 50)).toBe('waiting') // not long enough yet
    expect(feed(ends, 0.5, 1050 + ONSET_MS, 3000)).toBe('speech')
    expect(ends.heard()).toBe(true)
    expect(feed(ends, 0.01, 3050, 3050 + SILENCE_MS - 50)).toBe('speech') // a pause shorter than 1.2 s
    expect(ends.push(0.01, 3050 + SILENCE_MS)).toBe('end')
    expect(ends.push(0.9, 3100 + SILENCE_MS)).toBe('end') // stays ended
  })

  it('a short pause between words does not end the round', () => {
    const ends = endpointer(0)
    feed(ends, 0.5, 0, 600)
    expect(feed(ends, 0.02, 650, 1400)).toBe('speech')
    expect(feed(ends, 0.4, 1450, 2000)).toBe('speech')
    expect(feed(ends, 0.02, 2050, 2050 + SILENCE_MS - 50)).toBe('speech')
  })

  it('a click or a cough shorter than the onset time is not speech', () => {
    const ends = endpointer(0)
    feed(ends, 0.9, 0, 100)
    expect(feed(ends, 0.01, 150, 2000)).toBe('waiting')
    expect(ends.heard()).toBe(false)
  })

  it('at 15 s it ends: "end" with speech, "nothing" without', () => {
    const quiet = endpointer(0)
    expect(feed(quiet, 0.03, 0, LISTEN_MS - 50)).toBe('waiting')
    expect(quiet.push(0.03, LISTEN_MS)).toBe('nothing')
    const talking = endpointer(0)
    expect(feed(talking, 0.5, 0, LISTEN_MS - 50)).toBe('speech') // never paused
    expect(talking.push(0.5, LISTEN_MS)).toBe('end')
  })

  it('a steady hum between the two levels neither starts nor ends speech', () => {
    const ends = endpointer(0)
    expect(feed(ends, 0.1, 0, 5000)).toBe('waiting')
    feed(ends, 0.5, 5050, 5600)
    expect(feed(ends, 0.1, 5650, 9000)).toBe('speech')
  })
})

const done = (id: number, extra: Partial<Answer> = {}): Turn => ({
  kind: 'ask',
  id,
  question: 'q',
  answer: {
    ...EMPTY_ANSWER,
    status: 'done',
    meta: { language: 'fi' } as Answer['meta'],
    done: { answer_id: 'ans_1', text_rendered: 'Käytit 10 €.' } as Answer['done'],
    ...extra,
  },
})

describe('followAnswer (#811)', () => {
  it('follows the first ask turn after the id it was sent at, skipping older turns and client turns', () => {
    const turns: Turn[] = [done(1), { kind: 'client', id: 2, key: 'bill', question: 'Bill', render: 'bill' }]
    expect(followAnswer(turns, 2)).toEqual({ state: 'waiting' })
    turns.push({ kind: 'ask', id: 3, question: 'q', answer: EMPTY_ANSWER })
    expect(followAnswer(turns, 2)).toEqual({ state: 'waiting' }) // still streaming
    turns[2] = done(3)
    expect(followAnswer(turns, 2)).toEqual({ state: 'done', id: 3, text: 'Käytit 10 €.', answerId: 'ans_1', language: 'fi' })
  })

  it('an error or a stop says so', () => {
    expect(followAnswer([done(1, { status: 'error', done: null })], 0)).toEqual({ state: 'failed' })
    expect(followAnswer([done(1, { status: 'stopped', done: null })], 0)).toEqual({ state: 'stopped' })
  })
})

describe('waveBars (#811)', () => {
  it('gives the count of bars, mirrored around the middle, louder bands taller, within 0..1', () => {
    const frequencies = Array.from({ length: 64 }, (_, i) => Math.max(0, 255 - i * 8))
    const bars = waveBars(frequencies, 21)
    expect(bars).toHaveLength(21)
    expect(bars[0]).toBeCloseTo(bars[20])
    expect(bars[10]).toBeGreaterThan(bars[0])
    expect(Math.max(...bars)).toBeLessThanOrEqual(1)
    expect(waveBars(new Array(64).fill(0), 20).every((bar) => bar === 0)).toBe(true)
    expect(waveBars(frequencies, 20)).toHaveLength(20)
  })
})
