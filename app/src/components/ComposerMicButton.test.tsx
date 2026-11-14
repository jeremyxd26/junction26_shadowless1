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

  it('a live build shows a 44 px mic named in the language, with no motion until it records', async () => {
    const en = await render(true, true)
    expect(en).toContain('aria-label="Speak your question"')
    expect(en).toContain('size-[44px]')
    expect(en).not.toContain('animate-')
    const fi = await render(true, true, 'fi')
    expect(fi).toContain('aria-label="Sano kysymyksesi"')
  })

  it('the recording bar (#751): cancel, a waveform from the levels, the timer and stop, all 44 px', async () => {
    vi.resetModules()
    const { RecordingBar } = await import('./ComposerMicButton.tsx')
    const bar = (props: { sending: boolean; lang: 'en' | 'fi' }) =>
      renderToStaticMarkup(createElement(RecordingBar, { ...props, levels: [0.5, 1], elapsed: 3200, onCancel: () => {}, onStop: () => {} }))
    const en = bar({ sending: false, lang: 'en' })
    expect(en).toContain('aria-label="Cancel recording"')
    expect(en).toContain('aria-label="Stop and transcribe"')
    expect(en).toContain('0:03')
    expect(en.match(/size-\[44px\]/g)).toHaveLength(2)
    expect(en).toContain('height:28px')              // the loudest level fills the bar
    expect(en).toContain('height:14px')
    // Reduced motion: the bars are hidden and a still dot with "Recording" shows instead.
    expect(en).toContain('motion-reduce:hidden')
    expect(en).toContain('motion-reduce:inline-flex')
    expect(en).not.toContain('disabled=""')
    const fi = bar({ sending: true, lang: 'fi' })
    expect(fi).toContain('aria-label="Peru nauhoitus"')
    expect(fi).toContain('aria-label="Lopeta ja kirjoita teksti"')
    expect(fi).toContain('disabled=""')              // stop waits while the clip is turned into text
    expect(fi.match(/motion-safe:animate-pulse/g)).toHaveLength(3)   // the three dots, still under reduced motion
    expect(fi).not.toContain('height:28px')
  })
})
