import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Language, OverviewResponse, SafeToSaveCard } from '../../api/types.ts'
import contract from '../../api/mock/contract-examples.json'
import { strings } from '../../lib/i18n.ts'
import { OpeningContext, type Opening } from '../../lib/openingContext.ts'
import { SettingsContext } from '../../lib/settings.ts'
import { EMPTY_ANSWER } from '../../lib/answer.ts'
import { lastAskId, type Turn } from '../../lib/thread.ts'
import { TurnView } from '../AnswerView.tsx'
import { clientTurns, openingChips, type ClientTurnProps } from '../clientTurns.tsx'
import { inSentence, lessonOne, lessonsFor, lessonThree, lessonTwo, opensOnReveal, periodSpan, revealOf } from './lessons.ts'
import { lessonStrings } from './lessonStrings.ts'
import { LessonTurn } from './LessonTurn.tsx'
import turnSource from './LessonTurn.tsx?raw'
import lessonsSource from './lessons.ts?raw'

// Server rendering needs a server snapshot for the URL and reduced-motion stores; reuse the client one.
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return {
    ...react,
    useSyncExternalStore: <T,>(subscribe: (onChange: () => void) => () => void, snapshot: () => T) =>
      react.useSyncExternalStore(subscribe, snapshot, snapshot),
  }
})

const examples = contract.examples as unknown as Record<string, OverviewResponse>
const sanna = examples['overview.response_pending']
const aino = examples['overview.response']
const noHero = examples['overview.response_no_hero']
const clone = (overview: OverviewResponse): OverviewResponse => JSON.parse(JSON.stringify(overview))
/** An overview with nothing to teach from: no hero, no baskets card, no safe to save. */
const bare = (): OverviewResponse => ({ ...clone(noHero), hero: null, safe_to_save: null, cards: [] })
const displays = (overview: OverviewResponse | null) => lessonOne(overview)?.options.map((option) => [option.source, option.number.display])

// The props a client turn gets; `onBusy` arrives with #694, so the object fits with and without it.
const props = { turnId: 3, onStep: () => {}, onBusy: () => {} } as unknown as ClientTurnProps

function render(overview: OverviewResponse | null, lang: Language = 'en') {
  const opening = { overview } as unknown as Opening
  return renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: 'CUST00860', t: strings(lang) }}>
      <OpeningContext.Provider value={opening}>
        <LessonTurn {...props} />
      </OpeningContext.Provider>
    </SettingsContext.Provider>,
  )
}

describe('lesson 1: the options come from their source fields (#703)', () => {
  it('Sanna: weekly saving, safe to spend (the right one) and regular essentials, by display', () => {
    expect(displays(sanna)).toEqual([
      ['weekly', '€83.78 a week'],
      ['hero', '€138.79'],
      ['essentials', '€1,889.04 a month'],
    ])
    const lesson = lessonOne(sanna)!
    expect(lesson.right.source).toBe('hero')
    expect(lesson.right.number).toBe(sanna.hero!.primary)
    expect(lesson.span).toBe('week')
  })

  it('Aino: the same fields, her own numbers', () => {
    expect(displays(aino)).toEqual([
      ['weekly', '€99.25 a week'],
      ['hero', '€184.68'],
      ['essentials', '€1,180.21 a month'],
    ])
  })

  it('equal displays show once, and the right one is the one kept', () => {
    const same = clone(sanna)
    same.safe_to_save!.weekly = { ...same.safe_to_save!.weekly!, display: same.hero!.primary.display }
    expect(displays(same)).toEqual([
      ['hero', '€138.79'],
      ['essentials', '€1,889.04 a month'],
    ])
  })

  it('is hidden without a hero, with nothing free, or with no overview', () => {
    expect(lessonOne(noHero)).toBeNull()
    const nothing = clone(sanna)
    nothing.hero!.status = 'nothing_free'
    expect(lessonOne(nothing)).toBeNull()
    expect(lessonOne(null)).toBeNull()
  })

  it('with fewer than two options it opens on the reveal', () => {
    const only = clone(sanna)
    only.safe_to_save = null
    only.cards = []
    const lesson = lessonOne(only)!
    expect(lesson.options).toHaveLength(1)
    expect(opensOnReveal(lesson)).toBe(true)
    expect(opensOnReveal(lessonOne(sanna)!)).toBe(false)
  })

  it('says "this month" when the hero covers a month', () => {
    expect(periodSpan({ start: '2026-10-01', end: '2026-10-07', label: 'Next 7 days' })).toBe('week')
    expect(periodSpan({ start: '2026-10-01', end: '2026-10-31', label: 'October 2026' })).toBe('month')
  })
})

describe('lesson 1: the reveal', () => {
  const lesson = lessonOne(sanna)!

  it('a right pick, a wrong pick in kind words, and each other option by its label', () => {
    const en = lessonStrings('en')
    expect(revealOf(lesson, 'hero').verdict).toBe('right')
    expect(en.one.right.week('€138.79')).toBe("Right: €138.79 is what's left to spend this week.")
    expect(revealOf(lesson, 'weekly').verdict).toBe('close')
    expect(en.one.close.week('€138.79')).toBe("Close. €138.79 is what's left to spend this week.")
    const others = revealOf(lesson, 'essentials').others.map((option) => en.isLabel(option.number.display, inSentence(option.number.label)))
    expect(others).toEqual(['€83.78 a week is typically left each week.', '€1,889.04 a month is regular essentials.'])
    expect(en.one.concept).toBe('Left to spend is the money that stays yours after your regular bills and your saving are taken care of.')
  })

  it('keeps an acronym or a name at the start of a label', () => {
    expect(inSentence('S-Bonus benefit')).toBe('S-Bonus benefit')
    expect(inSentence('EU average')).toBe('EU average')
  })
})

describe('the lesson turn (#703)', () => {
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

  it('is registered as a client turn, "Lesson of the day" / "Päivän oppitunti"; the Learn tab replaced its opening chip', () => {
    expect(openingChips).not.toContain('lesson')
    expect(clientTurns.lesson.visible()).toBe(true)
    expect(clientTurns.lesson.chip('en')).toBe('Lesson of the day')
    expect(clientTurns.lesson.chip('fi')).toBe('Päivän oppitunti')
  })

  it('asks with a focusable step heading and a named group of 44 px answer buttons', () => {
    const html = render(sanna)
    expect(html).toMatch(/<h3 id="[^"]+" data-step-heading="" tabindex="-1"[^>]*>How much can you safely spend this week\?<\/h3>/)
    expect(html).toContain('role="group" aria-label="Your answer"')
    for (const display of ['€83.78 a week', '€138.79', '€1,889.04 a month']) {
      expect(html).toMatch(new RegExp(`<button type="button" class="min-h-11[^"]*">${display.replace(/[.$]/g, '\\$&')}</button>`))
    }
    // Sanna has all three lessons today.
    expect(html).toContain('>Lesson 1 of 3</p>')
  })

  it('in Finnish', () => {
    const html = render(sanna, 'fi')
    expect(html).toContain('Paljonko voit turvallisesti käyttää tällä viikolla?')
    expect(html).toContain('aria-label="Vastauksesi"')
  })

  it('opening on the reveal: the right number opens its evidence, or is plain text without a ref', () => {
    const only = clone(sanna)
    only.safe_to_save = null
    only.cards = []
    const html = render(only)
    expect(html).not.toContain('role="group"')
    expect(html).toContain('data-step-heading="" tabindex="-1"')
    expect(html).toContain(">€138.79 is what&#x27;s left to spend this week.</h3>")
    expect(html).toMatch(/<button type="button" aria-label="Safe to spend: €138\.79\. Show how it was calculated" class="[^"]*min-h-11[^"]*">€138\.79<\/button>/)
    only.hero!.primary = { ...only.hero!.primary, evidence_ref: null }
    const plain = render(only)
    expect(plain).not.toContain('<button')
    expect(plain).toContain('<span class="font-semibold tabular-nums text-ink">€138.79</span>')
  })

  it('a profile without a lesson gets one sentence, never an empty turn, in EN and FI', () => {
    for (const [lang, overview] of [['en', bare()], ['fi', bare()], ['en', null]] as const) {
      const html = render(overview, lang)
      expect(html).toContain(`data-step-heading="" tabindex="-1"`)
      expect(html).toContain(lessonStrings(lang).none)
    }
    expect(lessonStrings('en').none).toBe('No lesson for this profile today. Ask me anything below.')
  })

  it('formats no number, keeps no storage and draws no NumberChip', () => {
    for (const source of [turnSource, lessonsSource]) {
      expect(source).not.toMatch(/toFixed|NumberFormat|toLocaleString|localStorage|sessionStorage|indexedDB|NumberChip/)
    }
  })

  // The answer streaming above a lesson keeps its announcement because `latest` is the last ask
  // turn, not the last turn (#694: `lastAskId`, which Chat.tsx uses).
  it("pushing the lesson while an answer streams neither cuts nor repeats the answer's announcement", () => {
    const turns: Turn[] = [
      { kind: 'ask', id: 1, question: 'Where did my money go?', answer: EMPTY_ANSWER },
      { kind: 'client', id: 2, key: 'lesson', question: lessonStrings('en').chip, render: 'lesson' },
    ]
    expect(EMPTY_ANSWER.status).toBe('streaming')
    expect(lastAskId(turns)).toBe(1)
    const opening = { overview: sanna } as unknown as Opening
    const html = renderToStaticMarkup(
      <SettingsContext.Provider value={{ lang: 'en', customerId: 'CUST00860', t: strings('en') }}>
        <OpeningContext.Provider value={opening}>
          {turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} latest={turn.id === lastAskId(turns)} suggestions={[]} onAsk={() => {}} onRetry={() => {}} />
          ))}
        </OpeningContext.Provider>
      </SettingsContext.Provider>,
    )
    const announced = '<p role="status" class="sr-only">Reading your question</p>'
    expect(html.split(announced)).toHaveLength(2)
    // The lesson turn has its own status region, after the answer's.
    expect(html.indexOf('data-client-turn="lesson"')).toBeGreaterThan(html.indexOf(announced))
  })
})

describe('lesson 2: where the money goes (#704)', () => {
  it('the three basket labels, each with its share display, in the basket row order', () => {
    expect(lessonTwo(sanna)?.rows.map((row) => [row.key, row.label, row.display])).toEqual([
      ['regular_essentials', 'Regular essentials', '62.7%'],
      ['unexpected_necessities', 'Unexpected necessities', '11.3%'],
      ['everyday_spending', 'Everyday spending', '19.9%'],
    ])
  })

  it('the amount display when a basket has no share, and hidden without the three baskets', () => {
    const noShare = clone(aino)
    const card = noShare.cards.find((c) => c.type === 'breakdown') as unknown as { items: { key: string; share: unknown }[] }
    card.items[0].share = null
    expect(lessonTwo(noShare)?.rows[0].display).toBe('€1,180.21 a month')
    const missing = clone(aino)
    const missingCard = missing.cards.find((c) => c.type === 'breakdown') as unknown as { items: { key: string }[] }
    missingCard.items = missingCard.items.filter((item) => item.key !== 'everyday_spending')
    expect(lessonTwo(missing)).toBeNull()
    expect(lessonTwo(bare())).toBeNull()
  })

  it('reveals with no verdict and the three-basket concept, EN and FI', () => {
    expect(lessonStrings('en').two.reveal).toBe('Here is how your spending splits:')
    expect(lessonStrings('en').two.concept).toBe(
      'Sentti sorts spending into three baskets: regular essentials you pay every month, unexpected necessities you must pay but cannot plan, and everyday spending you choose.',
    )
    expect(lessonStrings('fi').two.reveal).toBe('Näin kulutuksesi jakautuu:')
  })
})

describe('lesson 3: how much can you set aside (#704)', () => {
  it('monthly, weekly (the right one) and safe to spend, by display', () => {
    const lesson = lessonThree(sanna)!
    expect(lesson.options.map((option) => [option.source, option.number.display])).toEqual([
      ['monthly', '€364.31 a month'],
      ['weekly', '€83.78 a week'],
      ['hero', '€138.79'],
    ])
    expect(lesson.right.source).toBe('weekly')
    expect(revealOf(lesson, 'weekly').verdict).toBe('right')
    expect(revealOf(lesson, 'hero').verdict).toBe('close')
    expect(lessonStrings('en').three.right('€83.78 a week')).toBe('Right: €83.78 a week is what you can set aside each week.')
    expect(lessonStrings('en').three.concept).toBe('Pay yourself first: the saving goes aside first, and everyday spending comes from what is left.')
  })

  it('carries the reason of a month that leaves nothing, and is hidden without safe to save or weekly', () => {
    const zero = clone(sanna)
    zero.safe_to_save = (contract.examples as unknown as Record<string, SafeToSaveCard>)['card.safe_to_save_zero']
    const lesson = lessonThree(zero)!
    expect(lesson.reason?.amount.display).toBe('€1.59 a month')
    expect(lesson.reason?.text).toMatch(/^Nothing is left in a typical month/)
    const noWeekly = clone(sanna)
    noWeekly.safe_to_save = { ...noWeekly.safe_to_save!, weekly: undefined }
    expect(lessonThree(noWeekly)).toBeNull()
    expect(lessonThree(bare())).toBeNull()
  })
})

describe('today\'s lessons in one turn (#704)', () => {
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

  it('Sanna and Aino get lessons 1, 2 and 3; a profile without a hero gets 2 and 3; nothing to teach from gets none', () => {
    expect(lessonsFor(sanna).map((lesson) => lesson.id)).toEqual([1, 2, 3])
    expect(lessonsFor(aino).map((lesson) => lesson.id)).toEqual([1, 2, 3])
    expect(lessonsFor(noHero).map((lesson) => lesson.id)).toEqual([2, 3])
    expect(lessonsFor(bare())).toEqual([])
  })

  it('without a hero the turn starts at lesson 2: "Lesson 1 of 2", the basket question with the three labels', () => {
    const html = render(noHero)
    expect(html).toContain('>Lesson 1 of 2</p>')
    expect(html).toContain('>Which basket takes the biggest part of your money?</h3>')
    for (const label of ['Regular essentials', 'Unexpected necessities', 'Everyday spending']) expect(html).toContain(`</span>${label}</button>`)
  })

  it('"Next lesson" and the end of the day, EN and FI', () => {
    expect(lessonStrings('en').next).toBe('Next lesson')
    expect(lessonStrings('en').done).toBe("That's all for today. Ask me anything below.")
    expect(lessonStrings('fi').next).toBe('Seuraava oppitunti')
  })
})
