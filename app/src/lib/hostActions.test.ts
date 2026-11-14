import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HANDOVER_EVENT, handOver, type HandOverDetail } from './hostActions.ts'
import type { HostScope } from './hostBridge.ts'

const PAYLOAD = { amount: '24.90', iban: 'FI2112345600000785' }
const MESSAGE = { type: 'sentti.paymentDraft', v: 1, payload: PAYLOAD }

function listen() {
  const names: string[] = []
  const onEvent = (event: Event) => names.push((event as CustomEvent<HandOverDetail>).detail.name)
  window.addEventListener(HANDOVER_EVENT, onEvent)
  return { names, stop: () => window.removeEventListener(HANDOVER_EVENT, onEvent) }
}

describe('handOver', () => {
  let stop = () => {}
  // The tests run in Node: a bare EventTarget stands in for `window`.
  beforeEach(() => {
    vi.stubGlobal('window', new EventTarget())
  })
  afterEach(() => {
    stop()
    vi.unstubAllGlobals()
  })

  it('posts the envelope as an object on iOS and fires no notice', () => {
    const postMessage = vi.fn()
    const events = listen()
    stop = events.stop
    expect(handOver('paymentDraft', PAYLOAD, { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope)).toBe(true)
    expect(postMessage).toHaveBeenCalledWith(MESSAGE)
    expect(events.names).toEqual([])
  })

  it('posts the envelope as a JSON string on Android and fires no notice', () => {
    const postMessage = vi.fn()
    const events = listen()
    stop = events.stop
    expect(handOver('paymentDraft', PAYLOAD, { sentti: { postMessage } } as HostScope)).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(typeof postMessage.mock.calls[0][0]).toBe('string')
    expect(JSON.parse(postMessage.mock.calls[0][0] as string)).toEqual(MESSAGE)
    expect(events.names).toEqual([])
  })

  it('returns false without a host and fires the notice event with the message name', () => {
    const events = listen()
    stop = events.stop
    expect(handOver('openHostScreen', { screen: 'savings' }, {})).toBe(false)
    expect(events.names).toEqual(['openHostScreen'])
  })

  it('returns false and fires the notice event when the host handler throws', () => {
    const events = listen()
    stop = events.stop
    const postMessage = vi.fn(() => {
      throw new Error('host failed')
    })
    expect(handOver('paymentDraft', PAYLOAD, { sentti: { postMessage } } as HostScope)).toBe(false)
    expect(events.names).toEqual(['paymentDraft'])
  })
})
