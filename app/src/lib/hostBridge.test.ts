import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, hostPlatform, sendToHost, type HostScope } from './hostBridge.ts'
import { canGoBack, goBack } from './url.ts'

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

  it('sends to iOS only when both host objects exist', () => {
    const ios = iosHost()
    const android = androidHost()
    const scope = { ...ios.scope, ...android.scope } as HostScope
    expect(hostPlatform(scope)).toBe('ios')
    expect(sendToHost('close', {}, scope)).toBe(true)
    expect(ios.postMessage).toHaveBeenCalledTimes(1)
    expect(android.postMessage).not.toHaveBeenCalled()
  })
})

/** A stubbed page: path, query, history state and any host objects. */
function page(pathname: string, state: Record<string, unknown> | null, extra: Record<string, unknown> = {}, search = '') {
  const back = vi.fn()
  const pushState = vi.fn()
  vi.stubGlobal('window', {
    history: { state, back, pushState, replaceState: vi.fn() },
    location: { pathname, search, href: `https://sentti.test${pathname}${search}`, origin: 'https://sentti.test' },
    dispatchEvent: vi.fn(),
    ...extra,
  })
  return { back, pushState }
}

describe('goBack', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends sentti.close to the iOS host on the first screen, and no longer the old { type: "close" }', () => {
    const { scope, postMessage } = iosHost()
    const { back } = page('/', null, scope as Record<string, unknown>)
    goBack()
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith(CLOSE)
    expect(postMessage).not.toHaveBeenCalledWith({ type: 'close' })
    expect(back).not.toHaveBeenCalled()
  })

  it('sends sentti.close to the Android host on the first screen', () => {
    const { scope, postMessage } = androidHost()
    const { back } = page('/', null, scope as Record<string, unknown>)
    goBack()
    expect(JSON.parse(postMessage.mock.calls[0][0] as string)).toEqual(CLOSE)
    expect(back).not.toHaveBeenCalled()
  })

  it('treats the overview as the first screen also after Chat → overview ({ screen: true })', () => {
    const { scope, postMessage } = iosHost()
    const { back, pushState } = page('/', { screen: true }, scope as Record<string, unknown>)
    goBack()
    expect(postMessage).toHaveBeenCalledWith(CLOSE)
    expect(back).not.toHaveBeenCalled()
    expect(pushState).not.toHaveBeenCalled()
  })

  it('does nothing on the first screen when the host handler throws', () => {
    const scope = { sentti: { postMessage: () => { throw new Error('closed') } } }
    const { back, pushState } = page('/', null, scope)
    goBack()
    expect(back).not.toHaveBeenCalled()
    expect(pushState).not.toHaveBeenCalled()
  })

  it('closes an open sheet on the overview instead of leaving the module', () => {
    const { scope, postMessage } = iosHost()
    const { back } = page('/', { sheet: true }, scope as Record<string, unknown>, '?evidence=ev_1')
    goBack()
    expect(back).toHaveBeenCalledTimes(1)
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('leaves an inner screen through the history, or to the overview when deep-linked', () => {
    const inner = page('/chat', { screen: true })
    goBack()
    expect(inner.back).toHaveBeenCalledTimes(1)
    const deep = page('/chat', null)
    goBack()
    expect(deep.back).not.toHaveBeenCalled()
    expect(deep.pushState).toHaveBeenCalledWith({ screen: true }, '', '/')
  })
})

describe('canGoBack: whether the header shows the back button', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hides it on the first screen of a plain browser', () => {
    page('/', null)
    expect(canGoBack()).toBe(false)
  })

  it('hides it on the overview without a host also after Chat → overview ({ screen: true })', () => {
    page('/', { screen: true })
    expect(canGoBack()).toBe(false)
  })

  it('shows it on the first screen inside the iOS or the Android host', () => {
    page('/', null, iosHost().scope as Record<string, unknown>)
    expect(canGoBack()).toBe(true)
    page('/', { screen: true }, androidHost().scope as Record<string, unknown>)
    expect(canGoBack()).toBe(true)
  })

  it('shows it on inner screens and over sheets, with or without a host', () => {
    page('/chat', { screen: true })
    expect(canGoBack()).toBe(true)
    page('/', { sheet: true })
    expect(canGoBack()).toBe(true)
    page('/', null, {}, '?evidence=ev_1')
    expect(canGoBack()).toBe(true)
    page('/chat', null)
    expect(canGoBack()).toBe(true)
  })
})
