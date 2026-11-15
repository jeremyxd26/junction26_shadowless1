// Reduced motion (#881): the global rule in index.css shortens every animation to 1 ms but keeps its
// iteration count, so an infinite Tailwind animation would cycle every millisecond (a jitter). Each one
// in the app must be gated with `motion-safe:`, so under reduced motion its element simply stands still.
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob('../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Tailwind's infinite animations used as a class without the `motion-safe:` gate. */
function bareInfinite(source: string): string[] {
  return [...source.matchAll(/(?<![\w:-])animate-(spin|pulse|ping|bounce)\b/g)].map((match) => match[0])
}

describe('infinite animations under reduced motion (#881)', () => {
  it('finds the sources to check', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20)
  })

  it('every animate-spin / pulse / ping / bounce is gated with motion-safe:', () => {
    const found = Object.entries(sources)
      .filter(([path]) => !path.endsWith('.test.tsx'))
      .flatMap(([path, source]) => bareInfinite(source).map((name) => `${path}: ${name}`))
    expect(found).toEqual([])
  })

  it('tells a gated class from a bare one', () => {
    expect(bareInfinite('className="size-6 motion-safe:animate-spin rounded-pill"')).toEqual([])
    expect(bareInfinite('className="size-6 animate-spin rounded-pill"')).toEqual(['animate-spin'])
    expect(bareInfinite("className='h-12 animate-pulse'")).toEqual(['animate-pulse'])
    expect(bareInfinite('`mt-3 ${on ? "animate-ping" : ""}`')).toEqual(['animate-ping'])
  })
})
