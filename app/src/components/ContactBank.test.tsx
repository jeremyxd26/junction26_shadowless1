import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readAskStream } from '../api/askStream.ts'
import contract from '../api/mock/contract-examples.json'
import { mockAsk } from '../api/mock/mockAsk.ts'
import type { AskEvent } from '../api/types.ts'
import { EMPTY_ANSWER, applyAskEvent, doneActions, type Answer } from '../lib/answer.ts'
import { hostScreenTarget, openHostScreen } from '../lib/hostActions.ts'
import type { HostScope } from '../lib/hostBridge.ts'
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

const DISCLOSURE = 'Explanations are written by AI. The numbers are calculated from your transactions.'
const request = { customer_id: 'CUST00042', language: 'en' as const, message: 'Should I put my savings into tech stocks?' }

async function answerOf(conversation_id: string | null): Promise<Answer> {
  const events: AskEvent[] = []
  for await (const event of readAskStream(await mockAsk({ ...request, conversation_id }))) events.push(event)
  return events.reduce(applyAskEvent, EMPTY_ANSWER)
}

const render = (answer: Answer) =>
  renderToStaticMarkup(<TurnView turn={{ kind: 'ask', id: 1, question: request.message, answer }} latest suggestions={[]} onAsk={() => {}} onRetry={() => {}} />)

describe('contract 0.3.3 in the thread (#439, security review #457 row 2)', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }))
    vi.stubGlobal('window', {
      location: new URL('http://localhost/?mock=refusal'),
      matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
      addEventListener() {},
      removeEventListener() {},
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('knows contact_bank, and still nothing else', () => {
    expect(hostScreenTarget('contact_bank')).toBe('contact_bank')
    expect(hostScreenTarget('contact_support')).toBeNull()
  })

  it('a refusal draws the "Contact S-Pankki" chip (44 px), and its tap sends exactly {target: "contact_bank"}', async () => {
    const answer = await answerOf(null)
    expect(answer.done?.outcome).toBe('refused')
    const html = render(answer)
    expect(html).toMatch(/<button type="button" class="[^"]*min-h-11[^"]*">Contact S-Pankki<\/button>/)

    // The chip's tap: the action from `done`, through the same closed list and hand-over.
    const [action] = doneActions(answer.done)
    expect(action).toEqual({ type: 'open_host_screen', label: 'Contact S-Pankki', target: 'contact_bank' })
    const postMessage = vi.fn()
    const target = hostScreenTarget((action as { target: string }).target)!
    expect(openHostScreen(target, { scope: { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope })).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage.mock.calls[0][0]).toStrictEqual({ type: 'sentti.openHostScreen', v: 1, payload: { target: 'contact_bank' } })
  }, 15000)

  it('the first answer shows the AI disclosure once, in the API words; a later answer does not', async () => {
    const first = render(await answerOf(null))
    expect(first.split(DISCLOSURE)).toHaveLength(2)
    const later = render(await answerOf('conv_7m3p9r2t'))
    expect(later).not.toContain(DISCLOSURE)
    // The later refusal still offers the way to the bank.
    expect(later).toContain('>Contact S-Pankki</button>')
  }, 15000)

  it('the contract examples carry the fields as 0.3.3 describes them', () => {
    const examples = contract.examples as unknown as Record<string, { actions: unknown[]; ai_disclosure: string | null }>
    expect(examples['ask.json.response_refusal_first'].ai_disclosure).toBe(DISCLOSURE)
    expect(examples['ask.json.response_refusal'].ai_disclosure).toBeNull()
    expect(examples['ask.json.response_refusal'].actions).toHaveLength(1)
  })
})
