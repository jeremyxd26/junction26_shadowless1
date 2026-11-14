// The composer mic (#735): only in a live build with a microphone API; a 44 px button with one name.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { strings } from '../lib/i18n.ts'

async function render(live: boolean, recorder: boolean, lang: 'en' | 'fi' = 'en') {
  vi.stubEnv('VITE_API_MODE', live ? 'live' : 'mock')
  vi.resetModules()
  vi.stubGlobal('window', recorder ? { MediaRecorder: class {} } : {})
  vi.stubGlobal('navigator', recorder ? { mediaDevices: { getUserMedia: () => Promise.reject(new Error('x')) } } : {})
  const { ComposerMicButton } = await import('./ComposerMicButton.tsx')
  const settings = await import('../lib/settings.ts')
  return renderToStaticMarkup(
    createElement(
      settings.SettingsContext,
      { value: { lang, customerId: 'CUST00860', t: strings(lang) } },
      createElement(ComposerMicButton, { onText: () => {} }),
    ),
  )
}

describe('ComposerMicButton (#735)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('a mock build shows no mic', async () => {
    expect(await render(false, true)).toBe('')
  })

  it('a browser without MediaRecorder shows no mic', async () => {
    expect(await render(true, false)).toBe('')
  })

  it('a live build shows a 44 px mic named in the language, not pressed, with no motion until it records', async () => {
    const en = await render(true, true)
    expect(en).toContain('aria-label="Speak your question"')
    expect(en).toContain('aria-pressed="false"')
    expect(en).toContain('size-[44px]')
    expect(en).not.toContain('animate-')
    const fi = await render(true, true, 'fi')
    expect(fi).toContain('aria-label="Sano kysymyksesi"')
  })
})
