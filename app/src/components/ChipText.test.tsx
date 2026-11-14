import { renderToStaticMarkup } from 'react-dom/server'
import contract from '../api/mock/contract-examples.json'
import { describe, expect, it } from 'vitest'
import { chipWrapping, displaySegments } from '../lib/displayParts.ts'
import { DisplayText } from './ChipText.tsx'

const render = (display: string) => renderToStaticMarkup(<DisplayText text={display} />)
const text = (html: string) => html.replace(/<[^>]+>/g, '')

describe('number chip wrapping (#493)', () => {
  it('can break only between the amount and the words after it, balanced', () => {
    const html = render('€780.00 a month')
    expect(html).toBe(
      '<span class="[text-wrap:balance]"><span class="whitespace-nowrap">€780.00 </span><wbr/><span class="whitespace-nowrap">a month</span></span>',
    )
    expect(displaySegments('€780.00 a month')).toEqual(['€780.00 ', 'a month'])
    expect(text(html)).toBe('€780.00 a month')
  })

  it('keeps a Finnish amount with its grouping spaces whole', () => {
    const html = render('1 080,55 € / kk')
    expect(html).toContain('<span class="whitespace-nowrap">1 080,55 € </span><wbr/><span class="whitespace-nowrap">/ kk</span>')
    expect(text(html)).toBe('1 080,55 € / kk')
  })

  it('leaves a plain amount as one unbreakable part', () => {
    expect(render('-€48.80')).toBe('<span class="[text-wrap:balance]"><span class="whitespace-nowrap">-€48.80</span></span>')
  })

  it('never wraps a chip in running text; a standalone chip wraps only past its max width', () => {
    expect(chipWrapping(true)).toBe('whitespace-nowrap')
    expect(chipWrapping(false)).toBe('shrink-0 max-w-full text-center')
  })

  it('breaks only after a segment that ends with a space, for every contract display', () => {
    const displays: string[] = []
    const walk = (value: unknown) => {
      if (Array.isArray(value)) value.forEach(walk)
      else if (typeof value === 'object' && value !== null) {
        const record = value as Record<string, unknown>
        if (typeof record.display === 'string') displays.push(record.display)
        Object.values(record).forEach(walk)
      }
    }
    walk(contract.examples)
    expect(displays.length).toBeGreaterThan(50)
    for (const display of displays) {
      const segments = displaySegments(display)
      expect(segments.join('')).toBe(display)
      for (const segment of segments.slice(0, -1)) expect(segment).toMatch(/\s$/)
      expect(text(render(display))).toBe(display.replace(/&/g, '&amp;'))
    }
    expect(displaySegments('72nd percentile')).toEqual(['72nd percentile'])
    expect(displaySegments('FI21 1234 5600 0007 85')).toEqual(['FI21 1234 5600 0007 85'])
  })
})
