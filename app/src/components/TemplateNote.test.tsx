// A template-written answer (warning llm_unavailable) shows no grey note any more (#941); the warning stays in done.
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readAskStream } from '../api/askStream.ts'
import { mockAsk } from '../api/mock/mockAsk.ts'
import type { AskEvent } from '../api/types.ts'
import { EMPTY_ANSWER, applyAskEvent } from '../lib/answer.ts'
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

describe('no template note in the thread (#941)', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/?mock=template'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders the template answer with its card and without the note', async () => {
    const events: AskEvent[] = []
    const request = { customer_id: 'CUST00042', conversation_id: null, language: 'en' as const, message: 'Where did my money go?' }
    for await (const event of readAskStream(await mockAsk(request))) events.push(event)
    const answer = events.reduce(applyAskEvent, EMPTY_ANSWER)
    expect(answer.done?.warnings).toContain('llm_unavailable')
    const html = renderToStaticMarkup(
      <TurnView turn={{ kind: 'ask', id: 1, question: request.message, answer }} latest suggestions={[]} onAsk={() => {}} onRetry={() => {}} />,
    )
    expect(html).toContain('Here is what I found for September.')
    expect(html).not.toMatch(/standard template|vakiopohjalla|without the AI model/)
  }, 15000)
})
