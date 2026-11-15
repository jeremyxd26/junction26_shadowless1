import { describe, expect, it } from 'vitest'
import { bandText } from './personaBand.ts'

describe('the persona age band', () => {
  it('reads with an en dash, and from 65 up as 65+', () => {
    expect(bandText('18-24')).toBe('18\u201324')
    expect(bandText('35-44')).toBe('35\u201344')
    expect(bandText('65-74')).toBe('65+')
    expect(bandText('75+')).toBe('65+')
  })
})
