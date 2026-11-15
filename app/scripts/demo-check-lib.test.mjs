import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CHIP_ROW, SETTLE_MAX_MS, SETTLE_QUIET_MS, TEXT, downOnly, findBrowser, line, mainText, parseAmount, parseArgs, rowProblems, rowQuestions, settleStep } from './demo-check-lib.mjs'

describe('TEXT', () => {
  it('finds the hand-over action by the labels the app and the core use, in EN and FI', () => {
    expect(TEXT.en.saveAction.test('See monthly saving in S-mobiili')).toBe(true)
    expect(TEXT.fi.saveAction.test('Katso kuukausisäästäminen S-mobiilissa')).toBe(true)
    expect(TEXT.fi.saveAction.test('Avaa kuukausisäästö')).toBe(true)
    expect(TEXT.fi.saveAction.test('See monthly saving in S-mobiili')).toBe(true)
    expect(TEXT.en.saveAction.test('See September transactions')).toBe(false)
  })
  it('knows the Undo button in both languages', () => {
    expect(TEXT.en.undo.test('Undo')).toBe(true)
    expect(TEXT.fi.undo.test('Peru')).toBe(true)
    expect(TEXT.fi.undo.test('Kumoa')).toBe(true)
  })
})

describe('parseArgs', () => {
  it('takes the base URL and the defaults', () => {
    expect(parseArgs(['http://localhost:4173/'])).toEqual({ base: 'http://localhost:4173', lang: 'en', persona: 'CUST00860' })
  })
  it('takes --lang and --persona', () => {
    expect(parseArgs(['https://sentti.example', '--lang', 'fi', '--persona', 'CUST00042'])).toEqual({ base: 'https://sentti.example', lang: 'fi', persona: 'CUST00042' })
  })
  it('explains a bad call', () => {
    expect(parseArgs([]).error).toMatch(/base URL/)
    expect(parseArgs(['localhost:4173']).error).toMatch(/not an http/)
    expect(parseArgs(['http://x', '--lang', 'sv']).error).toMatch(/en or fi/)
    expect(parseArgs(['http://x', '--persona', 'Sanna']).error).toMatch(/CUST00860/)
    expect(parseArgs(['http://x', '--headed']).error).toMatch(/unknown option/)
  })
})

describe('findBrowser', () => {
  const cache = join('/home/me', 'Library', 'Caches', 'ms-playwright')
  const shell = (build) => join(cache, `chromium_headless_shell-${build}`, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell')
  const fs = (paths) => ({
    exists: (p) => paths.includes(p),
    list: (dir) => {
      if (dir !== cache) throw new Error('no such dir')
      return ['chromium_headless_shell-1200', 'chromium_headless_shell-1234', 'ffmpeg-1011']
    },
  })

  it('prefers DEMO_CHECK_BROWSER', () => {
    expect(findBrowser({ env: { DEMO_CHECK_BROWSER: '/opt/chrome' }, home: '/home/me', platform: 'darwin', ...fs(['/opt/chrome', shell(1234)]) })).toBe('/opt/chrome')
  })
  it('takes the newest headless shell in the playwright cache', () => {
    expect(findBrowser({ env: {}, home: '/home/me', platform: 'darwin', ...fs([shell(1200), shell(1234)]) })).toBe(shell(1234))
  })
  it('falls back to an installed Chrome, and returns null without one', () => {
    const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    expect(findBrowser({ env: {}, home: '/home/me', platform: 'darwin', ...fs([chrome]) })).toBe(chrome)
    expect(findBrowser({ env: {}, home: '/home/me', platform: 'darwin', ...fs([]) })).toBeNull()
  })
})

describe('parseAmount', () => {
  it('reads the English and Finnish forms', () => {
    expect(parseAmount('€1,080.42', 'en')).toBe(1080.42)
    expect(parseAmount('-€5.00', 'en')).toBe(-5)
    expect(parseAmount('1 080,42 €', 'fi')).toBe(1080.42)
    expect(parseAmount('138,79 €', 'fi')).toBe(138.79)
  })
  it('returns null for anything else', () => {
    expect(parseAmount('138,79 €', 'en')).toBeNull()
    expect(parseAmount('Loading…', 'en')).toBeNull()
    expect(parseAmount('', 'fi')).toBeNull()
  })
})

describe('downOnly', () => {
  it('passes a count that only goes down', () => {
    expect(downOnly([138.79, 138.79, 130.52, 116.74, 97.46, 97.46])).toEqual({ ok: true, from: 138.79, to: 97.46, steps: 3, upAt: -1 })
  })
  it('fails a count that goes up once, or does not move', () => {
    expect(downOnly([138.79, 120, 125, 97.46]).ok).toBe(false)
    expect(downOnly([138.79, 138.79]).ok).toBe(false)
  })
})

describe('line', () => {
  it('lines up the status', () => {
    expect(line(5, 'SKIP', 'x')).toBe('5 SKIP  x')
    expect(line(1, 'PASS', 'y')).toBe('1 PASS  y')
  })
})

describe('the opening chip row (#784, #788)', () => {
  it('finds the row inside the opening by its data-opening-part', () => {
    expect(CHIP_ROW).toBe('[data-turn="opening"] [data-opening-part="client-chips"]')
  })

  it('keeps the question chips, in row order, and leaves the client-turn chips out', () => {
    const en = ['Where did my money go?', 'How could I save more?', 'Show Sentti a bill', 'What can I safely spend this week? ']
    expect(rowQuestions(en)).toEqual(['Where did my money go?', 'How could I save more?', 'What can I safely spend this week?'])
    const fi = ['Mihin rahani menivät?', 'Miten voisin säästää enemmän?', 'Näytä Sentille lasku']
    expect(rowQuestions(fi)).toEqual(['Mihin rahani menivät?', 'Miten voisin säästää enemmän?'])
    expect(rowQuestions([])).toEqual([])
  })

  it('passes a row with the first question and another, and names what is missing', () => {
    expect(rowProblems(['Where did my money go?', 'How could I save more?'], TEXT.en.firstQuestion)).toEqual([])
    expect(rowProblems(['Mihin rahani menivät?', 'Miten voisin säästää enemmän?'], TEXT.fi.firstQuestion)).toEqual([])
    expect(rowProblems([], TEXT.en.firstQuestion)).toEqual(['0 question chips in the row, not 2 or more', 'no "Where did my money go?" chip in the row'])
    expect(rowProblems(['How could I save more?', 'Can I afford a dinner out?'], TEXT.en.firstQuestion)).toEqual(['no "Where did my money go?" chip in the row'])
  })
})

describe('an answer settles before step 4 measures it (#928)', () => {
  /** Runs settleStep over samples taken every 100 ms; returns the time it settled, or null. */
  function settleTime(samples) {
    let state = null
    for (const [i, look] of samples.entries()) {
      state = settleStep(state, look, i * 100)
      if (state.settled) return i * 100
    }
    return null
  }

  it('waits while the text types in and the cards wait behind the skeleton, then settles once quiet', () => {
    const typing = ['From', 'From 1 Apr', 'From 1 Apr – 30 Sep', 'From 1 Apr – 30 Sep 2026, your total'].map((text) => ({ text, skeleton: true }))
    const cardsIn = { text: 'From 1 Apr – 30 Sep 2026, your total … €3,010.59 a month', skeleton: false }
    // 4 typing samples (0–300 ms), then the cards (400 ms) and quiet: settled 500 ms after the last change.
    expect(settleTime([...typing, ...Array(8).fill(cardsIn)])).toBe(400 + SETTLE_QUIET_MS)
  })

  it('never settles while a skeleton shows, however long the text holds still', () => {
    const held = { text: 'Where did my money go?', skeleton: true }
    expect(settleTime(Array(20).fill(held))).toBeNull()
  })

  it('an answer without cards settles too: no skeleton and a quiet text is enough', () => {
    const refusal = { text: 'I can only look at your own money', skeleton: false }
    expect(settleTime(Array(8).fill(refusal))).toBe(SETTLE_QUIET_MS)
  })

  it('is bounded: the check waits at most 8 s for it', () => {
    expect(SETTLE_MAX_MS).toBe(8_000)
    expect(SETTLE_QUIET_MS).toBeLessThan(SETTLE_MAX_MS)
  })

  it('reports the first paragraph as the main sentence, not the longest one', () => {
    const takeaway = 'From 1 Apr – 30 Sep 2026, your total spending was €3,010.59 a month.'
    const note = 'Fixed costs like rent change slowly. Flexible costs like eating out are where quick change is possible, so look there first.'
    expect(mainText(['', `  ${takeaway} `, note])).toBe(takeaway)
    expect(mainText([])).toBe('')
  })
})
