import { describe, expect, it } from 'vitest'
import { splitKeepTogether } from './keepTogether.ts'

const NBSP = String.fromCharCode(160)

describe('runs the API joins with no-break spaces (#725)', () => {
  it('keeps "28 September 2026" as one run, with ordinary spaces, and the text around it as is', () => {
    const question = `€1,080.42 at Home & Tech on 28${NBSP}September${NBSP}2026 — needed, or your choice?`
    expect(splitKeepTogether(question)).toEqual([
      '€1,080.42 at Home & Tech on ',
      { together: '28 September 2026' },
      ' — needed, or your choice?',
    ])
  })

  it('leaves text without no-break spaces alone, Finnish dates included', () => {
    expect(splitKeepTogether('1 080,42 € Koti ja tekniikka, 28.9.2026 — välttämätön?')).toEqual([
      '1 080,42 € Koti ja tekniikka, 28.9.2026 — välttämätön?',
    ])
    expect(splitKeepTogether('')).toEqual([])
  })

  it('finds every joined run, at the start and the end too', () => {
    expect(splitKeepTogether(`1${NBSP}Oct and 28${NBSP}Sep`)).toEqual([{ together: '1 Oct' }, ' and ', { together: '28 Sep' }])
  })
})
