import { afterEach, describe, expect, it, vi } from 'vitest'
import { askInThread, redirectChatToThread } from './url.ts'

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
