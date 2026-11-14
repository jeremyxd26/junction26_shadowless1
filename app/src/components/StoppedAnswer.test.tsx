import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Language } from '../api/types.ts'
import { EMPTY_ANSWER, applyAskEvent, stopped, type Answer, type StopReason } from '../lib/answer.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { strings } from '../lib/i18n.ts'
import { SettingsContext } from '../lib/settings.ts'
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

const partial: Answer = applyAskEvent(EMPTY_ANSWER, { event: 'delta', data: { text: 'September cost ' } })

function render(answer: Answer, lang: Language) {
  return renderToStaticMarkup(
    <SettingsContext.Provider value={{ lang, customerId: 'CUST00860', t: strings(lang) }}>
      <TurnView turn={{ kind: 'ask', id: 1, question: 'Where did my money go?', answer }} latest={false} suggestions={[]} onAsk={() => {}} onRetry={() => {}} />
    </SettingsContext.Provider>,
  )
}

describe('an answer that stopped says why (#715)', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('marks only a streaming answer as stopped, with its reason, and keeps what it showed', () => {
    for (const reason of ['you', 'next_question'] as StopReason[]) {
      const answer = stopped(partial, reason)
      expect(answer.status).toBe('stopped')
      expect(answer.stoppedBy).toBe(reason)
      expect(answer.text).toBe('September cost ')
    }
    const done = { ...partial, status: 'done' as const }
    expect(stopped(done, 'next_question')).toBe(done)
  })

  it('says "You stopped this answer." only after Stop, and names the next question otherwise, in EN and FI', () => {
    for (const lang of ['en', 'fi'] as Language[]) {
      const s = chatStrings(lang)
      const byYou = render(stopped(partial, 'you'), lang)
      const byNext = render(stopped(partial, 'next_question'), lang)
      expect(byYou).toContain(s.stopped)
      expect(byYou).not.toContain(s.stoppedForNext)
      expect(byNext).toContain(s.stoppedForNext)
      expect(byNext).not.toContain(s.stopped)
      // Both can be asked again.
      expect(byNext).toContain(`>${s.askAgain}</button>`)
    }
    expect(chatStrings('en').stoppedForNext).toBe('Stopped for your next question.')
  })
})
