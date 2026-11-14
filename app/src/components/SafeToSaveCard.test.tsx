import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Card, Num, SafeToSaveCard as SafeToSaveData } from '../api/types.ts'
import contract from '../api/mock/contract-examples.json'
import { AnswerCard } from './AnswerCard.tsx'
import { SafeToSaveCard } from './SafeToSaveCard.tsx'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const examples = contract.examples as unknown as Record<string, unknown>
const SAVE_EXAMPLES = ['card.safe_to_save', 'card.safe_to_save_aleksi', 'card.safe_to_save_zero', 'card.safe_to_save_everyday']
const sanna = examples['card.safe_to_save'] as SafeToSaveData

/** The markup of the element that carries `attribute`, up to its closing `</div>` (no nested divs). */
function part(html: string, attribute: string): string {
  const start = html.indexOf(attribute)
  return start < 0 ? '' : html.slice(start, html.indexOf('</div>', start))
}

/** What a reader sees and hears in a `part`: its text without tags, plus every `aria-label`. */
function readable(markup: string): string {
  const inner = markup.slice(markup.indexOf('>') + 1)
  const labels = [...inner.matchAll(/aria-label="([^"]*)"/g)].map((match) => match[1])
  return [inner.replace(/<[^>]*>/g, ''), ...labels].join(' ')
}

/** A chip with evidence: a button named "<label>: <display>." that shows `display`. */
const chipButton = (number: Num) => new RegExp(`<button type="button" class="[^"]*" aria-label="${number.label}: ${number.display}\\.[^"]*">`)

describe('safe to save: the week and the day under the month (#477)', () => {
  // The tests run in Node: the chips read duration tokens, the URL and the reduced-motion setting.
  beforeAll(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterAll(() => vi.unstubAllGlobals())

  it('Sanna: "€42.46 a week · €6.07 a day" as two chips that open their evidence, after the month', () => {
    const html = renderToStaticMarkup(<SafeToSaveCard card={sanna} />)
    const scales = part(html, 'data-save-scales')
    expect(sanna.weekly?.display).toBe('€42.46 a week')
    expect(sanna.daily?.display).toBe('€6.07 a day')
    expect(scales).toMatch(chipButton(sanna.weekly!))
    expect(scales).toMatch(chipButton(sanna.daily!))
    expect(scales).toContain('>·</span>')
    // Smaller than the headline: inline chips (a 32 px pill with a 44 px hit area), and the month first.
    expect(scales).toContain('min-h-8')
    expect(html.indexOf(sanna.monthly.display)).toBeLessThan(html.indexOf('data-save-scales'))
  })

  it('every contract example shows its own week and day displays, unchanged', () => {
    for (const name of SAVE_EXAMPLES) {
      const card = examples[name] as SafeToSaveData
      const scales = part(renderToStaticMarkup(<SafeToSaveCard card={card} />), 'data-save-scales')
      // A standalone chip may break after the amount (<wbr>), so compare the text without tags.
      const shown = scales.slice(scales.indexOf('>') + 1).replace(/<[^>]*>/g, '')
      expect(shown).toBe(`${card.weekly!.display}·${card.daily!.display}`)
    }
  })

  it('an older API without weekly and daily still renders the card, with no empty line', () => {
    const older: SafeToSaveData = { ...sanna, weekly: undefined, daily: undefined }
    const html = renderToStaticMarkup(<SafeToSaveCard card={older} />)
    expect(html).toContain(sanna.monthly.display)
    expect(html).not.toContain('data-save-scales')
    // Only one of them: that chip, and no separator.
    const weekOnly = part(renderToStaticMarkup(<SafeToSaveCard card={{ ...older, weekly: sanna.weekly }} />), 'data-save-scales')
    expect(weekOnly).toMatch(chipButton(sanna.weekly!))
    expect(weekOnly).not.toContain('·')
  })

  it('nothing next to the S-mobiili button joins an amount and the bank: the actions row holds only the button', () => {
    expect(sanna.actions.some((action) => action.type === 'open_host_screen')).toBe(true)
    const actions = part(renderToStaticMarkup(<SafeToSaveCard card={sanna} />), 'data-card-actions')
    expect(readable(actions)).toContain('S-mobiili')
    expect(readable(actions)).not.toMatch(/[0-9€]/)
  })

  it('in a chat answer (#684): the month large, the week, the day and the stock as three rows, each opening its evidence, no actions', () => {
    const html = renderToStaticMarkup(<AnswerCard card={sanna as unknown as Card} />)
    expect(html.slice(html.indexOf('data-answer-main'))).toMatch(chipButton(sanna.monthly))
    for (const number of [sanna.weekly!, sanna.daily!, sanna.stock]) expect(html).toMatch(chipButton(number))
    expect(html.split('data-figure-row').length - 1).toBe(3)
    expect(html).not.toContain('data-card-actions')
    // The subtitle and the stock's explanation are sentences the answer already says.
    expect(html).not.toContain(sanna.stock_explanation)
  })
})
