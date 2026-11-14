import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handOver } from '../lib/hostActions.ts'
import type { HostScope } from '../lib/hostBridge.ts'
import { hostStrings } from '../lib/hostStrings.ts'
import appSource from '../App.tsx?raw'
import { onHandOverWithoutHost } from '../lib/hostNotice.ts'
import { HostNoticeView } from './HostNotice.tsx'

const view = (open: boolean, lang: 'en' | 'fi' = 'en') =>
  renderToStaticMarkup(<HostNoticeView open={open} text={hostStrings(lang).continuesInBankApp} onClose={() => {}} />)

describe('HostNotice (#431)', () => {
  // The tests run in Node: a bare EventTarget stands in for `window`.
  let shown = 0
  let stop = () => {}
  beforeEach(() => {
    shown = 0
    vi.stubGlobal('window', new EventTarget())
    stop = onHandOverWithoutHost(() => shown++)
  })
  afterEach(() => {
    stop()
    vi.unstubAllGlobals()
  })

  it('a hand-over in a plain browser fires the notice, and the notice renders the text in EN and FI', () => {
    expect(handOver('openHostScreen', { target: 'monthly_saving' }, { scope: {} })).toBe(false)
    expect(shown).toBe(1)
    const en = view(true)
    expect(en).toContain('role="status"')
    expect(en).toContain('>This continues in the bank app.</button>')
    expect(en).toContain('min-h-11')
    expect(view(true, 'fi')).toContain('>Tämä jatkuu pankin sovelluksessa.</button>')
  })

  it('a host stub that takes the message (the demo frame) shows nothing', () => {
    const postMessage = vi.fn()
    expect(handOver('openHostScreen', { target: 'monthly_saving' }, { scope: { sentti: { postMessage } } as HostScope })).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(shown).toBe(0)
  })

  it('a silent hand-over shows nothing', () => {
    handOver('openHostScreen', { target: 'monthly_saving' }, { scope: {}, silent: true })
    expect(shown).toBe(0)
  })

  it('closed, only the empty live region is rendered, so the text is announced once when it appears', () => {
    expect(view(false)).toBe(
      '<div class="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+88px)] z-[60] mx-auto flex max-w-[480px] justify-center px-4"><div role="status" aria-live="polite"></div></div>',
    )
  })

  it('is mounted exactly once, at the app root', () => {
    expect(appSource.match(/<HostNotice \/>/g)).toHaveLength(1)
  })
})
