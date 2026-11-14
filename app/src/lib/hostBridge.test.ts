import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, hostPlatform, sendToHost, type HostScope } from './hostBridge.ts'
import { goBack } from './url.ts'

const CLOSE = { type: 'sentti.close', v: 1, payload: {} }

function iosHost() {
  const postMessage = vi.fn()
  return { scope: { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope, postMessage }
}

function androidHost() {
  const postMessage = vi.fn()
  return { scope: { sentti: { postMessage } } as HostScope, postMessage }
}

describe('sendToHost', () => {
  it('builds the documented envelope', () => {
    expect(envelope('close')).toEqual(CLOSE)
    expect(envelope('openTransaction', { transaction_id: 'tx_606016' })).toEqual({
      type: 'sentti.openTransaction',
      v: 1,
      payload: { transaction_id: 'tx_606016' },
    })
  })

  it('posts the envelope as an object on iOS', () => {
    const { scope, postMessage } = iosHost()
    expect(hostPlatform(scope)).toBe('ios')
    expect(sendToHost('close', {}, scope)).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith(CLOSE)
  })

  it('posts the envelope as a JSON string on Android', () => {
    const { scope, postMessage } = androidHost()
    expect(hostPlatform(scope)).toBe('android')
    expect(sendToHost('close', {}, scope)).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    const [sent] = postMessage.mock.calls[0]
    expect(typeof sent).toBe('string')
    expect(JSON.parse(sent as string)).toEqual(CLOSE)
  })

  it('does nothing without a host (a plain browser)', () => {
    expect(hostPlatform({})).toBeNull()
    expect(sendToHost('close', {}, {})).toBe(false)
    expect(sendToHost('close', {}, { webkit: {} } as HostScope)).toBe(false)
  })

  it('reports false when the host handler throws, so the app can fall back', () => {
    const scope = { sentti: { postMessage: () => { throw new Error('closed') } } } as HostScope
    expect(sendToHost('close', {}, scope)).toBe(false)
  })
})

describe('goBack on the first screen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function firstScreen(extra: Record<string, unknown>) {
    const back = vi.fn()
    vi.stubGlobal('window', { history: { state: null, back }, location: { pathname: '/' }, ...extra })
    return back
  }

  it('sends sentti.close to the iOS host and no longer the old { type: "close" }', () => {
    const { scope, postMessage } = iosHost()
    const back = firstScreen(scope as Record<string, unknown>)
    goBack()
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith(CLOSE)
    expect(postMessage).not.toHaveBeenCalledWith({ type: 'close' })
    expect(back).not.toHaveBeenCalled()
  })

  it('sends sentti.close to the Android host', () => {
    const { scope, postMessage } = androidHost()
    const back = firstScreen(scope as Record<string, unknown>)
    goBack()
    expect(JSON.parse(postMessage.mock.calls[0][0] as string)).toEqual(CLOSE)
    expect(back).not.toHaveBeenCalled()
  })

  it('stays in the browser history when no host listens', () => {
    const back = firstScreen({})
    goBack()
    expect(back).toHaveBeenCalledTimes(1)
  })
})
