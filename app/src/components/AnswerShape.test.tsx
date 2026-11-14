import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { readAskStream } from '../api/askStream.ts'
import contract from '../api/mock/contract-examples.json'
import { pickStream } from '../api/mock/mockAsk.ts'
import type { AskEvent, Card } from '../api/types.ts'
import { EMPTY_ANSWER, applyAskEvent, type Answer } from '../lib/answer.ts'
import { TurnView } from './AnswerView.tsx'

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
const DISCLOSURE = (examples['ask.sse.done'] as { ai_disclosure: string }).ai_disclosure

/** A mock stream read through the real parser, without the mock's delays. */
async function answerOf(question: string, scenario: string | null = null, first = true): Promise<Answer> {
  const bytes = new TextEncoder().encode(`${pickStream(question, scenario, first).join('\n\n')}\n\n`)
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes)
      controller.close()
    },
  })
  const events: AskEvent[] = []
  for await (const event of readAskStream(stream)) events.push(event)
  return events.reduce(applyAskEvent, EMPTY_ANSWER)
}

const render = (question: string, answer: Answer, latest = true) => {
  // An asked turn (`kind: 'ask'` since #689's client turns).
  const turn = { kind: 'ask' as const, id: 1, question, answer }
  return renderToStaticMarkup(<TurnView turn={turn} latest={latest} suggestions={[]} onAsk={() => {}} onRetry={() => {}} />)
}

const count = (html: string, needle: string) => html.split(needle).length - 1
/** The markup without the screen readers' live region, which reads the whole answer once. */
const visible = (html: string) => html.replace(/<p role="status" class="sr-only">.*?<\/p>/s, '')
/** Text as it appears in the markup (an apostrophe is escaped). */
const escape = (text: string) => text.replaceAll("'", '&#x27;')
/** The markup inside `data-next-step`, up to its closing div. */
const stepOf = (html: string) => {
  const at = html.indexOf('data-next-step')
  return at < 0 ? '' : html.slice(at, html.indexOf('</div>', at))
}

const ROUTES = [
  'How could I save more?',
  'What can I safely spend this week?',
  'What if I spend 20% less on restaurants?',
  'What kind of spender am I?',
  'Where did my money go?',
]

describe('the answer reads once (#684, #685)', () => {
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

  for (const question of ROUTES) {
    it(`"${question}": no question repeat, no card title, the period once, at most 3 rows, no pills`, async () => {
      const answer = await answerOf(question)
      expect(answer.done?.outcome).toBe('answered')
      const html = render(question, answer)
      // The question only in the bubble; no card title that restates it (a peer title names what
      // is compared and stays, in the normal weight).
      expect(count(html, escape(question))).toBe(1)
      for (const card of answer.cards.filter((card) => card.type !== 'peer')) expect(html).not.toContain(`>${escape(card.title)}<`)
      expect(html).not.toContain('text-card-title font-bold')
      // Per card: the period once as a caption, and at most three rows under the main number.
      const sections = html.split('<section').slice(1)
      expect(sections).toHaveLength(answer.cards.length)
      for (const section of sections) {
        expect(count(section, 'data-answer-caption')).toBeLessThanOrEqual(1)
        expect(count(section, 'data-answer-main')).toBeLessThanOrEqual(1)
        expect(count(section, 'data-figure-row')).toBeLessThanOrEqual(3)
      }
      // No green pills: no mint number chips and no mint follow-up chips.
      expect(html).not.toContain('bg-mint-tint')
    })

    it(`"${question}": at most one next step, from the response`, async () => {
      const answer = await answerOf(question)
      const html = render(question, answer)
      expect(count(html, 'data-next-step')).toBeLessThanOrEqual(1)
      const step = stepOf(html)
      expect(count(step, '<button')).toBe(1)
      const offered = [
        ...answer.cards.flatMap((card: Card) => card.actions.map((action) => action.label)),
        ...(answer.done?.follow_ups ?? []),
      ].map(escape)
      expect(offered.some((label) => step.includes(`>${label}</button>`))).toBe(true)
    })

    it(`"${question}": no AI line and no source label on the answer`, async () => {
      const html = render(question, await answerOf(question))
      expect(html).not.toContain(DISCLOSURE)
      expect(html).not.toContain('From your transactions')
      expect(html).not.toContain('Tilitapahtumista')
    })
  }

  it('save more: the next step is the bank screen the demo path taps', async () => {
    const step = stepOf(render('How could I save more?', await answerOf('How could I save more?')))
    expect(step).toContain('>See monthly saving in S-mobiili</button>')
  })

  it('spender type: the answer sentence is not repeated in the card', async () => {
    const answer = await answerOf('What kind of spender am I?')
    const description = (examples['card.profile'] as { profile: { description: string } }).profile.description
    expect(answer.done?.text).toBe(description)
    expect(count(visible(render('What kind of spender am I?', answer)), escape(description))).toBe(1)
  })

  it('an older answer drops a follow-up step instead of swapping in another one', async () => {
    // The what-if card carries only "How is this calculated?", so its step is the first follow-up.
    const question = 'What if I spend 20% less on restaurants?'
    const answer = await answerOf(question)
    expect(stepOf(render(question, answer, true))).toContain(`>${answer.done!.follow_ups[0]}</button>`)
    expect(render(question, answer, false)).not.toContain('data-next-step')
  })

  it('an answer without actions or follow-ups shows no next step', async () => {
    const answer = await answerOf('What kind of spender am I?')
    const bare: Answer = {
      ...answer,
      cards: answer.cards.map((card) => ({ ...card, actions: [] })),
      done: { ...answer.done!, follow_ups: [], actions: [] },
    }
    expect(render('What kind of spender am I?', bare)).not.toContain('data-next-step')
  })

  it('a refusal keeps one way to the bank, and its first answer has no AI line', async () => {
    const question = 'Should I put my savings into tech stocks?'
    const answer = await answerOf(question, null, true)
    expect(answer.done?.ai_disclosure).toBe(DISCLOSURE)
    const html = render(question, answer)
    expect(html).not.toContain(DISCLOSURE)
    expect(count(html, 'data-next-step')).toBe(1)
    expect(stepOf(html)).toContain('>Contact S-Pankki</button>')
  })
})
