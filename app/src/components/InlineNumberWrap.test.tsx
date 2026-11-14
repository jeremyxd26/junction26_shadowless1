import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Num } from '../api/types.ts'
import { NumberChip } from './NumberChip.tsx'

// Server rendering needs a server snapshot for the reduced-motion store; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const month: Num = {
  value: 3010.59,
  unit: 'eur',
  period: null,
  method: 'sum@1',
  evidence_ref: 'ev_month',
  label: 'Typically spent each month',
  display: '€3,010.59 a month',
} as unknown as Num

describe('a number in an answer sentence at 200 % text (#726)', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('may break between the amount and its words, never inside the amount, and never past the line', () => {
    for (const tone of ['plain', 'mint'] as const) {
      const html = renderToStaticMarkup(<NumberChip number={month} size="inline" tone={tone} />)
      const button = /^<button[^>]*class="([^"]*)"/.exec(html)![1].split(' ')
      expect(button).toContain('max-w-full')
      expect(button).not.toContain('whitespace-nowrap')
      expect(html).toContain('<span class="whitespace-nowrap">€3,010.59 </span><wbr/><span class="whitespace-nowrap">a month</span>')
    }
  })

  it('keeps a Finnish display whole where it has no words to wrap before', () => {
    const html = renderToStaticMarkup(<NumberChip number={{ ...month, display: '3 010,59 € / kk' }} size="inline" tone="plain" />)
    expect(html).toContain('<span class="whitespace-nowrap">3 010,59 € </span><wbr/><span class="whitespace-nowrap">/ kk</span>')
  })
})
