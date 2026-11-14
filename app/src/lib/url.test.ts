import { afterEach, describe, expect, it, vi } from 'vitest'
import { askInThread, canGoBack, closeOverview, goBack, openOverview, overviewFromParams, redirectChatToThread } from './url.ts'

/** A stubbed page at `pathname` + `search`; the history records every replace and push. */
function page(pathname: string, search = '', state: Record<string, unknown> | null = null) {
  const replaceState = vi.fn()
  const pushState = vi.fn()
  const dispatchEvent = vi.fn()
  vi.stubGlobal('window', {
    history: { state, back: vi.fn(), pushState, replaceState },
    location: { pathname, search, href: `https://sentti.test${pathname}${search}`, origin: 'https://sentti.test' },
    dispatchEvent,
  })
  return { replaceState, pushState, dispatchEvent }
}

describe('askInThread', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('puts the question in ?q= on / by replacing the entry, keeping persona and language', () => {
    const { replaceState, pushState, dispatchEvent } = page('/', '?persona=CUST00860&lang=fi')
    askInThread('Where did my money go?')
    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
    const target = new URL(replaceState.mock.calls[0][2] as string, 'https://sentti.test')
    expect(target.pathname).toBe('/')
    expect(target.searchParams.get('q')).toBe('Where did my money go?')
    expect(target.searchParams.get('persona')).toBe('CUST00860')
    expect(target.searchParams.get('lang')).toBe('fi')
    expect(dispatchEvent).toHaveBeenCalledTimes(1)
  })

  it('asks from an old /chat path on / as well, and keeps the history state', () => {
    const { replaceState } = page('/chat', '?persona=CUST00860', { screen: true })
    askInThread('How could I save more?')
    const [state, , url] = replaceState.mock.calls[0]
    expect(state).toEqual({ screen: true })
    expect(new URL(url as string, 'https://sentti.test').pathname).toBe('/')
  })
})

describe('redirectChatToThread', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('replaces /chat with / and keeps the query, so Back never returns to /chat', () => {
    const { replaceState, pushState } = page('/chat', '?persona=CUST00860&q=Hi')
    redirectChatToThread()
    expect(pushState).not.toHaveBeenCalled()
    expect(replaceState).toHaveBeenCalledTimes(1)
    const target = new URL(replaceState.mock.calls[0][2] as string, 'https://sentti.test')
    expect(target.pathname).toBe('/')
    expect(target.search).toBe('?persona=CUST00860&q=Hi')
  })
})

describe('overview sheet (#321)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** A page inside an Android host, so `sentti.close` would reach `postMessage`. */
  function hosted(search: string, state: Record<string, unknown> | null) {
    const stubs = page('/', search, state)
    const postMessage = vi.fn()
    const win = globalThis.window as unknown as Record<string, unknown>
    win.sentti = { postMessage }
    return { ...stubs, back: (win.history as { back: ReturnType<typeof vi.fn> }).back, postMessage }
  }
  const query = (replaceState: ReturnType<typeof vi.fn>) =>
    new URL(replaceState.mock.calls[0][2] as string, 'https://sentti.test').searchParams

  it('opens as a history entry with ?overview=1, keeping persona and language', () => {
    const { pushState } = page('/', '?persona=CUST00860&lang=fi')
    openOverview()
    const [state, , url] = pushState.mock.calls[0]
    expect(state).toEqual({ sheet: true })
    const target = new URL(url as string, 'https://sentti.test')
    expect(target.searchParams.get('overview')).toBe('1')
    expect(target.searchParams.get('persona')).toBe('CUST00860')
  })

  it('reads ?overview=1 and nothing else as open', () => {
    expect(overviewFromParams(new URLSearchParams('overview=1'))).toBe(true)
    expect(overviewFromParams(new URLSearchParams('overview=0'))).toBe(false)
    expect(overviewFromParams(new URLSearchParams(''))).toBe(false)
  })

  it('closes with a step back when the app opened it, with a replace when it was deep-linked', () => {
    const opened = hosted('?overview=1', { sheet: true })
    closeOverview()
    expect(opened.back).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
    const linked = page('/', '?persona=CUST00860&overview=1')
    closeOverview()
    expect(query(linked.replaceState).has('overview')).toBe(false)
    expect(query(linked.replaceState).get('persona')).toBe('CUST00860')
  })

  it('Back on the first screen with the overview open closes it and never sends sentti.close', () => {
    const { back, postMessage } = hosted('?overview=1', { sheet: true })
    expect(canGoBack()).toBe(true)
    goBack()
    expect(back).toHaveBeenCalledTimes(1)
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('Back closes a deep-linked overview by replacing the entry, not by closing the module', () => {
    const { replaceState, postMessage } = hosted('?overview=1', null)
    goBack()
    expect(query(replaceState).has('overview')).toBe(false)
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('closes in the order evidence, then what-if, then overview', () => {
    const evidence = hosted('?overview=1&whatif=category:Restaurants&cut=20&evidence=ev_1', null)
    goBack()
    const afterEvidence = query(evidence.replaceState)
    expect([afterEvidence.has('evidence'), afterEvidence.has('whatif'), afterEvidence.has('overview')]).toEqual([false, true, true])
    vi.unstubAllGlobals()
    const whatIf = hosted('?overview=1&whatif=category:Restaurants&cut=20', null)
    goBack()
    const afterWhatIf = query(whatIf.replaceState)
    expect([afterWhatIf.has('whatif'), afterWhatIf.has('cut'), afterWhatIf.has('overview')]).toEqual([false, false, true])
    expect(whatIf.postMessage).not.toHaveBeenCalled()
  })

  it('Back on the first screen with no sheet still hands control to the host', () => {
    const { postMessage } = hosted('?persona=CUST00860', null)
    goBack()
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(JSON.parse(postMessage.mock.calls[0][0] as string).type).toBe('sentti.close')
  })
})
