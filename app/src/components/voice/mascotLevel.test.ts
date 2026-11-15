// Sentti's mascot (#798): the level that drives the mouth, without any audio.
import { describe, expect, it } from 'vitest'
import { LEVEL_GAIN, MOUTH_MAX_RY, levelFromAnalyser, levelSource, mouthRy, runMouth, smoothLevel, type FrameClock } from './mascotLevel.ts'

/** An AnalyserNode stand-in that writes one frame of a square wave around 128 (silence). */
function fakeAnalyser(amplitude: number) {
  let calls = 0
  return {
    get calls() {
      return calls
    },
    getByteTimeDomainData(buf: Uint8Array<ArrayBuffer>) {
      calls += 1
      for (let i = 0; i < buf.length; i++) buf[i] = 128 + (i % 2 === 0 ? amplitude : -amplitude)
    },
  }
}

describe('smoothLevel', () => {
  it('rises fast and falls slowly', () => {
    const up = smoothLevel(0, 1)
    const down = smoothLevel(1, 0)
    expect(up).toBeCloseTo(0.5)
    expect(1 - down).toBeCloseTo(0.12)
    expect(up).toBeGreaterThan(1 - down)
  })

  it('reaches a steady level and settles to exactly 0 in silence', () => {
    let level = 0
    for (let i = 0; i < 30; i++) level = smoothLevel(level, 0.6)
    expect(level).toBeCloseTo(0.6, 5)
    for (let i = 0; i < 120; i++) level = smoothLevel(level, 0)
    expect(level).toBe(0)
  })

  it('keeps to 0..1 and treats a broken input as silence', () => {
    expect(smoothLevel(0.5, 7)).toBeLessThanOrEqual(1)
    expect(smoothLevel(-3, -1)).toBe(0)
    expect(smoothLevel(Number.NaN, Number.NaN)).toBe(0)
    expect(smoothLevel(0.5, Number.POSITIVE_INFINITY)).toBeCloseTo(0.5 - 0.5 * 0.12)
  })
})

describe('mouthRy', () => {
  it('is shut when quiet and at most MOUTH_MAX_RY when loud', () => {
    expect(mouthRy(0)).toBe(0)
    expect(mouthRy(0.01)).toBe(0)
    expect(mouthRy(1)).toBe(MOUTH_MAX_RY)
    expect(mouthRy(4)).toBe(MOUTH_MAX_RY)
    expect(mouthRy(-1)).toBe(0)
    expect(mouthRy(Number.NaN)).toBe(0)
    expect(MOUTH_MAX_RY).toBeLessThanOrEqual(5)
  })

  it('opens with the level, rounded to 0.01', () => {
    expect(mouthRy(0.5)).toBe(2.5)
    expect(mouthRy(0.333)).toBe(1.67)
    const steps = [0.1, 0.2, 0.4, 0.8].map(mouthRy)
    expect(steps).toEqual([...steps].sort((a, b) => a - b))
  })
})

describe('levelFromAnalyser', () => {
  it('reads one frame into the given buffer: silence is 0', () => {
    const analyser = fakeAnalyser(0)
    const buf = new Uint8Array(512)
    expect(levelFromAnalyser(analyser, buf)).toBe(0)
    expect(analyser.calls).toBe(1)
  })

  it('is the RMS with the mic meter gain (x4), clamped to 1', () => {
    expect(LEVEL_GAIN).toBe(4)
    // A square wave of ±8 has an RMS of 8/128 = 0.0625, x4 = 0.25.
    expect(levelFromAnalyser(fakeAnalyser(8), new Uint8Array(256))).toBeCloseTo(0.25)
    expect(levelFromAnalyser(fakeAnalyser(16), new Uint8Array(256))).toBeCloseTo(0.5)
    // ±64 would be 2: clamped.
    expect(levelFromAnalyser(fakeAnalyser(64), new Uint8Array(256))).toBe(1)
  })

  it('an empty buffer is silence', () => {
    expect(levelFromAnalyser(fakeAnalyser(40), new Uint8Array(0))).toBe(0)
  })
})

/** A frame clock driven by hand: `tick()` runs the one pending frame, as the browser would. */
function handClock() {
  let pending: (() => void) | null = null
  let id = 0
  const cancelled: number[] = []
  const clock: FrameClock = {
    request(step) {
      pending = step
      return ++id
    },
    cancel(frame) {
      cancelled.push(frame)
      pending = null
    },
  }
  return {
    clock,
    cancelled,
    get id() {
      return id
    },
    tick() {
      const step = pending
      pending = null
      step?.()
    },
  }
}

describe('levelSource (#893)', () => {
  it('polls getLevel when the parent gives one, and uses the level prop otherwise', () => {
    expect(levelSource(undefined, 0.4)).toBe(0.4)
    let calls = 0
    const getLevel = () => {
      calls++
      return 0.9
    }
    expect(levelSource(getLevel, 0.4)).toBe(0.9)
    expect(levelSource(getLevel, 0.4)).toBe(0.9)
    expect(calls).toBe(2)
  })
})

describe('runMouth (#893)', () => {
  it('the getLevel path: each frame reads the getter anew, so the mouth moves with no new props', () => {
    const frames = handClock()
    const levels = [0, 1, 1, 0.5, 0]
    let at = 0
    const shown: string[] = []
    runMouth(() => levelSource(() => levels[Math.min(at++, levels.length - 1)], 0), (ry) => shown.push(ry), frames.clock)
    for (let i = 0; i < levels.length; i++) frames.tick()
    // Silence keeps it shut (no write); the attack opens it at once; the release closes it slowly.
    expect(shown[0]).toBe(String(mouthRy(smoothLevel(0, 1))))
    expect(shown.length).toBeGreaterThanOrEqual(3)
    expect(Number(shown[1])).toBeGreaterThan(Number(shown[0]))
    expect(Number(shown.at(-1))).toBeLessThan(Number(shown[1]))
    expect(Number(shown.at(-1))).toBeGreaterThan(0)
  })

  it('the level-prop path: a steady level opens the mouth and writes only when the shown value changes', () => {
    const frames = handClock()
    const shown: string[] = []
    runMouth(() => levelSource(undefined, 0.6), (ry) => shown.push(ry), frames.clock)
    for (let i = 0; i < 40; i++) frames.tick()
    expect(shown.at(-1)).toBe(String(mouthRy(0.6)))
    // Converging on 0.6 writes a handful of values, then nothing while it holds.
    const before = shown.length
    for (let i = 0; i < 10; i++) frames.tick()
    expect(shown.length).toBe(before)
  })

  it('the stop cancels the pending frame and shuts the mouth', () => {
    const frames = handClock()
    const shown: string[] = []
    const stop = runMouth(() => 1, (ry) => shown.push(ry), frames.clock)
    frames.tick()
    stop()
    expect(frames.cancelled).toEqual([frames.id])
    expect(shown.at(-1)).toBe('0')
    frames.tick()
    expect(shown.at(-1)).toBe('0')
  })
})
