// Voice mode (#811): the send button turns into the voice-mode button with an empty input, and the overlay.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { strings } from '../lib/i18n.ts'
import type { ChatSession } from '../lib/useChat.ts'

const chat: ChatSession = {
  turns: [],
  busy: false,
  send: () => {},
  retry: () => {},
  stop: () => {},
  pushClientTurn: () => null,
  clear: () => {},
}

function stub(live: boolean, recorder: boolean) {
  vi.stubEnv('VITE_API_MODE', live ? 'live' : 'mock')
  vi.resetModules()
  vi.stubGlobal('window', recorder ? { MediaRecorder: class {} } : {})
  vi.stubGlobal('navigator', recorder ? { mediaDevices: { getUserMedia: () => Promise.reject(new Error('x')) } } : {})
}

async function renderChat(live: boolean, recorder: boolean, lang: 'en' | 'fi' = 'en', busy = false) {
  stub(live, recorder)
  const { Chat } = await import('../screens/Chat.tsx')
  const settings = await import('../lib/settings.ts')
  return renderToStaticMarkup(
    createElement(
      settings.SettingsContext,
      { value: { lang, customerId: 'CUST00860', t: strings(lang) } },
      createElement(Chat, { chat: { ...chat, busy }, question: null, disclosure: 'AI', suggestions: [] }),
    ),
  )
}

describe('the send button with an empty input (#811)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('opens voice mode in a live build with a microphone API: a plain button with the wave shown, the arrow faded', async () => {
    const en = await renderChat(true, true)
    expect(en).toMatch(/<button type="button" aria-label="Start voice mode" class="[^"]*size-\[44px\]/)
    expect(en).not.toContain('aria-label="Send"')
    // Both icons are there for the cross-fade; the arrow is the hidden one, without motion when reduced.
    expect(en.match(/scale-50 opacity-0/g)).toHaveLength(1)
    expect(en.match(/scale-100 opacity-100/g)).toHaveLength(1)
    expect(en).toContain('motion-reduce:transition-none')
    const fi = await renderChat(true, true, 'fi')
    expect(fi).toContain('aria-label="Aloita puhetila"')
  })

  it('stays the send arrow in a mock build or without a microphone API, and the stop button while an answer streams', async () => {
    for (const markup of [await renderChat(false, true), await renderChat(true, false)]) {
      expect(markup).toMatch(/<button type="submit" aria-label="Send"/)
      expect(markup).not.toContain('Start voice mode')
    }
    const busy = await renderChat(true, true, 'en', true)
    expect(busy).toContain('aria-label="Stop the answer"')
    expect(busy).not.toContain('Start voice mode')
  })
})

describe('the voice-mode overlay (#811)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  async function renderOverlay(lang: 'en' | 'fi') {
    stub(true, true)
    const { VoiceMode, WAVE_BARS } = await import('./VoiceMode.tsx')
    const { VoiceSession } = await import('../lib/voiceSession.ts')
    const settings = await import('../lib/settings.ts')
    const session = new VoiceSession({ customerId: 'CUST00860', lang, ask: () => {}, closed: () => {} }, null, [])
    const markup = renderToStaticMarkup(
      createElement(settings.SettingsContext, { value: { lang, customerId: 'CUST00860', t: strings(lang) } }, createElement(VoiceMode, { session, turns: [] })),
    )
    return { markup, bars: WAVE_BARS }
  }

  it('is a named modal dialog with a wave button, one status caption and a 56 px End button', async () => {
    const { markup, bars } = await renderOverlay('en')
    expect(markup).toContain('role="dialog"')
    expect(markup).toContain('aria-modal="true"')
    expect(markup).toContain('aria-labelledby="voice-mode-title"')
    expect(markup).toContain('id="voice-mode-title"')
    expect(markup).toContain('>Voice mode</h2>')
    expect(markup.match(/role="status"/g)).toHaveLength(1)
    expect(markup).toContain('Listening…')
    // Before the microphone is open, the wave cannot be tapped yet.
    expect(markup).toContain('aria-disabled="true"')
    expect(markup).toMatch(/min-h-\[56px\][^>]*>.*End voice mode<\/button>/)
    expect(markup.match(/origin-center rounded-full bg-brand/g)).toHaveLength(bars)
  })

  it('under reduced motion the moving bars hide and a still ring shows; Finnish strings', async () => {
    const { markup } = await renderOverlay('fi')
    expect(markup).toContain('motion-reduce:hidden')
    expect(markup).toContain('motion-reduce:block')
    expect(markup).not.toContain('animate-')
    expect(markup).toContain('>Puhetila</h2>')
    expect(markup).toContain('Kuuntelen…')
    expect(markup).toContain('Lopeta puhetila</button>')
  })
})
