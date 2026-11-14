import { describe, expect, it } from 'vitest'
import { billStrings } from './billStrings.ts'

/** Every string value, functions called with a placeholder. */
function texts(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (typeof value === 'function') return texts((value as (arg: string) => unknown)('x'))
  if (typeof value === 'object' && value !== null) return Object.values(value).flatMap(texts)
  return []
}

describe('bill strings', () => {
  it('never call a bill a fraud: warning signs are signs, not a verdict', () => {
    for (const lang of ['en', 'fi'] as const) {
      const all = texts(billStrings(lang)).join('\n')
      expect(all).not.toMatch(/fraud|scam|huijaus|petos/i)
    }
  })

  it('have the same keys in English and Finnish', () => {
    expect(Object.keys(billStrings('fi')).sort()).toEqual(Object.keys(billStrings('en')).sort())
  })
})
