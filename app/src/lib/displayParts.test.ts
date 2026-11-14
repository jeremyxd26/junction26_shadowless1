import { describe, expect, it } from 'vitest'
import contract from '../api/mock/contract-examples.json'
import { displayParts } from './displayParts.ts'

const amounts = (display: string) => displayParts(display).filter((part) => part.amount).map((part) => part.text)

describe('displayParts', () => {
  it.each([
    ['€1,080.55 a month', ['€1,080.55']],
    ['1 080,55 € / kk', ['1 080,55 €']],
    ['€812.40', ['€812.40']],
    ['812,40 €', ['812,40 €']],
    ['-€48.80', ['-€48.80']],
    ['4.2%', ['4.2%']],
    ['4,2 %', ['4,2 %']],
    ['€12,360.83', ['€12,360.83']],
    ['12 360,83 € / v', ['12 360,83 €']],
    ['3 months', ['3']],
  ])('keeps the amount of %j in one part', (display, expected) => {
    expect(amounts(display)).toEqual(expected)
  })

  it('never changes the text: the parts join back to every display of the contract examples', () => {
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
    for (const display of displays) expect(displayParts(display).map((part) => part.text).join('')).toBe(display)
  })

  it('leaves the words after the amount free to wrap', () => {
    expect(displayParts('€780.00 a month')).toEqual([
      { text: '€780.00', amount: true },
      { text: ' a month', amount: false },
    ])
  })
})
