// The Gemini voice of a live build (#730): POST /api/tts, Web Audio playback, device-voice fallback.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Speech = typeof import('./speech.ts')

const voice = { lang: 'en-GB', name: 'Daniel', localService: true } as unknown as SpeechSynthesisVoice
const remote = { customerId: 'CUST00860', answerId: 'ans_aaaa1111', language: 'en' as const }

class FakeUtterance {
  voice: SpeechSynthesisVoice | null = null
  lang = ''
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly text: string) {}
}

class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  started = 0
  stopped = 0
  connect() {}
  start() {
    this.started += 1
  }
  stop() {
    this.stopped += 1
  }
}

const sources: FakeSource[] = []

class FakeAudioContext {
  destination = {}
  resume() {
    return Promise.resolve()
  }
  decodeAudioData(data: ArrayBuffer) {
    return Promise.resolve({ length: data.byteLength })
  }
  createBufferSource() {
    const source = new FakeSource()
    sources.push(source)
    return source
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('speakAnswer in a live build', () => {
  const spoken: FakeUtterance[] = []
  let speech: Speech

  beforeEach(async () => {
    spoken.length = 0
    sources.length = 0
    vi.stubEnv('VITE_API_MODE', 'live')
    vi.resetModules()
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    vi.stubGlobal('window', {
      speechSynthesis: { cancel: () => {}, speak: (u: FakeUtterance) => spoken.push(u) },
      AudioContext: FakeAudioContext,
    })
    speech = await import('./speech.ts')
  })
  afterEach(() => {
    speech.stopSpeaking()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('asks the core for our answer by id and plays the audio, not the device voice', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) })
    vi.stubGlobal('fetch', fetchSpy)
    speech.speakAnswer('7', 'Groceries were 412.30 EUR.', voice, remote)
    expect(speech.speakingNow()).toBe('7')
    await flush()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/tts')
    expect(JSON.parse(init.body)).toEqual({ customer_id: 'CUST00860', answer_id: 'ans_aaaa1111', language: 'en' })
    expect(sources).toHaveLength(1)
    expect(sources[0].started).toBe(1)
    expect(spoken).toHaveLength(0)
    sources[0].onended?.()
    expect(speech.speakingNow()).toBeNull()
  })

  it('shows "preparing" at once on the tap and clears it when the audio plays', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) }))
    speech.speakAnswer('7', 'Text.', voice, remote)
    expect(speech.usePreparingId).toBeTypeOf('function')
    await flush()
    expect(sources).toHaveLength(1)
  })

  it('plays a voice fetched ahead without a second request', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, headers: { get: () => 'ok' }, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) })
    vi.stubGlobal('fetch', fetchSpy)
    speech.prefetchVoice(remote)
    speech.prefetchVoice(remote)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    await flush()
    speech.speakAnswer('7', 'Text.', voice, remote)
    await flush()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(sources).toHaveLength(1)
    expect(sources[0].started).toBe(1)
  })

  it('stops fetching ahead once the core says the budget is low', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, headers: { get: () => 'low' }, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) })
    vi.stubGlobal('fetch', fetchSpy)
    speech.prefetchVoice(remote)
    await flush()
    speech.prefetchVoice({ ...remote, answerId: 'ans_bbbb2222' })
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('falls back to the device voice on an error answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    speech.speakAnswer('7', 'Groceries were 412.30 EUR.', voice, remote)
    await flush()
    expect(spoken.map((u) => u.text)).toEqual(['Groceries were 412.30 EUR.'])
    expect(sources).toHaveLength(0)
  })

  it('falls back on a network failure, and goes idle without a device voice', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    speech.speakAnswer('7', 'Text.', null, remote)
    await flush()
    expect(spoken).toHaveLength(0)
    expect(speech.speakingNow()).toBeNull()
  })

  it('uses the device voice without an answer id', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    speech.speakAnswer('7', 'Text.', voice, null)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(spoken).toHaveLength(1)
  })

  it('never plays a response that arrives after a stop', async () => {
    let answer: (value: unknown) => void = () => {}
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise((resolve) => (answer = resolve))))
    speech.speakAnswer('7', 'Text.', voice, remote)
    speech.stopSpeaking('7')
    answer({ ok: true, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) })
    await flush()
    expect(sources).toHaveLength(0)
    expect(spoken).toHaveLength(0)
    expect(speech.speakingNow()).toBeNull()
  })

  it('stops the playing audio when stopped', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) }))
    speech.speakAnswer('7', 'Text.', voice, remote)
    await flush()
    speech.stopSpeaking('7')
    expect(sources[0].stopped).toBe(1)
    expect(speech.speakingNow()).toBeNull()
  })
})
