// The composer mic's request and helpers (#735): POST /api/stt with the clip, the error mapping, the draft.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { micStrings } from './micStrings.ts'
import { SttFailed, micFailure, pickType, transcribe, withSpoken, type SttFailure } from './stt.ts'
import { MAX_QUESTION } from './useChat.ts'

const clip = new Blob([new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3])], { type: 'audio/webm;codecs=opus' })

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function failure(promise: Promise<unknown>): Promise<SttFailure | null> {
  try {
    await promise
    return null
  } catch (error) {
    return error instanceof SttFailed ? error.reason : null
  }
}

describe('transcribe (#735)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts the clip with its type, the customer and the language, and returns the words', async () => {
    const fetchMock = respond(200, { text: '  How much did I spend on food? ', language: 'en' })
    await expect(transcribe(clip, 'CUST00860', 'en')).resolves.toBe('How much did I spend on food?')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/stt?customer_id=CUST00860&language=en')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('audio/webm;codecs=opus')
    expect(init.body).toBe(clip)
  })

  it('maps the envelopes to short reasons', async () => {
    respond(429, { error: { code: 'rate_limited' } })
    expect(await failure(transcribe(clip, 'CUST00860', 'en'))).toBe('busy')
    respond(413, { error: { code: 'invalid_request' } })
    expect(await failure(transcribe(clip, 'CUST00860', 'en'))).toBe('too_long')
    respond(400, { error: { code: 'invalid_request' } })
    expect(await failure(transcribe(clip, 'CUST00860', 'fi'))).toBe('no_speech')
    respond(503, { error: { code: 'model_unavailable' } })
    expect(await failure(transcribe(clip, 'CUST00860', 'en'))).toBe('unavailable')
    respond(200, { text: '' })
    expect(await failure(transcribe(clip, 'CUST00860', 'en'))).toBe('no_speech')
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('offline'))))
    expect(await failure(transcribe(clip, 'CUST00860', 'en'))).toBe('unavailable')
  })
})

describe('mic helpers (#735)', () => {
  it('picks WebM/Opus first, MP4 on Safari, and lets the browser choose when none fits', () => {
    expect(pickType(() => true)).toBe('audio/webm;codecs=opus')
    expect(pickType((type) => type === 'audio/mp4')).toBe('audio/mp4')
    expect(pickType(() => false)).toBe('')
    expect(
      pickType(() => {
        throw new Error('old browser')
      }),
    ).toBe('')
  })

  it('a refused permission is "denied", anything else "no_mic"', () => {
    expect(micFailure(new DOMException('no', 'NotAllowedError'))).toBe('denied')
    expect(micFailure(new DOMException('no', 'SecurityError'))).toBe('denied')
    expect(micFailure(new DOMException('none', 'NotFoundError'))).toBe('no_mic')
    expect(micFailure('odd')).toBe('no_mic')
  })

  it('the words go after what is typed, within the composer limit', () => {
    expect(withSpoken('', ' How much? ')).toBe('How much?')
    expect(withSpoken('About food: ', 'how much?')).toBe('About food: how much?')
    expect(withSpoken('x'.repeat(490), 'and one more question')).toHaveLength(MAX_QUESTION)
  })

  it('every reason has a short message in English and Finnish, and the button its name', () => {
    expect(micStrings('en').speak).toBe('Speak your question')
    expect(micStrings('fi').speak).toBe('Sano kysymyksesi')
    for (const lang of ['en', 'fi'] as const) {
      for (const text of Object.values(micStrings(lang).failures)) expect(text.length).toBeLessThan(90)
    }
  })
})
