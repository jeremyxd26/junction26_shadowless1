// One voice-mode conversation (#811): listen, ask, speak, listen again, and its fallbacks. The microphone,
// the recorder, /api/stt and the voice are fakes; time is fake.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_ANSWER, type Answer } from './answer.ts'
import type { Turn } from './thread.ts'

const speech = vi.hoisted(() => {
  const listeners = new Set<() => void>()
  const state = {
    speaking: null as string | null,
    budgetLow: false,
    calls: [] as { id: string; text: string; remote: unknown; voice: unknown }[],
    prefetched: [] as unknown[],
    stops: 0,
  }
  const notify = () => listeners.forEach((listener) => listener())
  return { listeners, state, notify }
})

vi.mock('./speech.ts', () => ({
  TTS_LIVE: true,
  prefetchVoice: (remote: unknown) => speech.state.prefetched.push(remote),
  readOutput: () => false,
  speakAnswer: (id: string, text: string, voice: unknown, remote: unknown) => {
    speech.state.calls.push({ id, text, voice, remote })
    speech.state.speaking = id
    speech.notify()
  },
  speakingNow: () => speech.state.speaking,
  stopSpeaking: () => {
    speech.state.stops += 1
    speech.state.speaking = null
    speech.notify()
  },
  subscribeSpeaking: (listener: () => void) => {
    speech.listeners.add(listener)
    return () => speech.listeners.delete(listener)
  },
  voiceBudgetLow: () => speech.state.budgetLow,
}))

let loud = false
const recorders: FakeRecorder[] = []
const tracks = { stopped: 0 }

class FakeRecorder {
  static isTypeSupported = (type: string) => type === 'audio/webm;codecs=opus'
  mimeType = 'audio/webm;codecs=opus'
  state = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  constructor() {
    recorders.push(this)
  }
  start() {
    this.state = 'recording'
  }
  stop() {
    if (this.state === 'inactive') throw new Error('InvalidStateError')
    this.state = 'inactive'
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(['x'.repeat(4000)]) })
      this.onstop?.()
    })
  }
}

const fakeContext = () =>
  ({
    createAnalyser: () => ({
      fftSize: 0,
      smoothingTimeConstant: 0,
      // 8-bit samples around 128: loud swings by 32 (level 1.0 after scaling), quiet stays flat.
      getByteTimeDomainData: (frame: Uint8Array) => frame.forEach((_, i) => (frame[i] = loud ? (i % 2 ? 160 : 96) : 128)),
      getByteFrequencyData: (frame: Uint8Array) => frame.fill(loud ? 200 : 0),
    }),
    createMediaStreamSource: () => ({ connect: () => {} }),
    resume: () => Promise.resolve(),
    close: () => Promise.resolve(),
  }) as unknown as AudioContext

const voice = { lang: 'en-GB', localService: true } as unknown as SpeechSynthesisVoice

/** A microphone stream; `echoCancellation`: what the browser reports it applied. */
function micStream(echoCancellation: boolean) {
  const track = { stop: () => (tracks.stopped += 1), getSettings: () => ({ echoCancellation }) }
  return { getTracks: () => [track], getAudioTracks: () => [track] }
}

function doneTurn(id: number, extra: Partial<Answer> = {}): Turn {
  return {
    kind: 'ask',
    id,
    question: 'How much did I spend?',
    answer: {
      ...EMPTY_ANSWER,
      status: 'done',
      meta: { language: 'en' } as Answer['meta'],
      done: { answer_id: 'ans_7', text_rendered: 'You spent €42.' } as Answer['done'],
      ...extra,
    },
  }
}

describe('VoiceSession (#811)', () => {
  let fetchCalls: string[]
  let sttReply: () => Promise<unknown>
  let micReply: (constraints?: unknown) => Promise<unknown>

  beforeEach(() => {
    vi.useFakeTimers()
    loud = false
    recorders.length = 0
    tracks.stopped = 0
    speech.state.speaking = null
    speech.state.budgetLow = false
    speech.state.calls = []
    speech.state.prefetched = []
    speech.state.stops = 0
    speech.listeners.clear()
    fetchCalls = []
    sttReply = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ text: 'How much did I spend?' }) })
    micReply = () => Promise.resolve(micStream(true))
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('document', { hidden: false, addEventListener: () => {}, removeEventListener: () => {} })
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: (constraints: unknown) => micReply(constraints) } })
    vi.stubGlobal('MediaRecorder', FakeRecorder)
    vi.stubGlobal('fetch', (url: string) => {
      fetchCalls.push(url)
      return sttReply()
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  async function open(turns: Turn[] = []) {
    const { VoiceSession } = await import('./voiceSession.ts')
    const asked: string[] = []
    const closed: unknown[] = []
    const session = new VoiceSession(
      { customerId: 'CUST00860', lang: 'en', ask: (q) => asked.push(q), closed: (reason) => closed.push(reason ?? 'exit') },
      fakeContext(),
      turns,
    )
    session.setVoice(voice)
    void session.start()
    await vi.advanceTimersByTimeAsync(0)
    return { session, asked, closed }
  }

  /** Speaks for 0.6 s, then stays quiet until the round ends. */
  async function sayAQuestion() {
    loud = true
    await vi.advanceTimersByTimeAsync(600)
    loud = false
    await vi.advanceTimersByTimeAsync(1400)
  }

  it('listens, sends the words as a question, reads the answer with the fetched-ahead Gemini voice, then listens again', async () => {
    const { session, asked, closed } = await open([doneTurn(1)])
    expect(session.getSnapshot().phase).toBe('listening')
    await sayAQuestion()
    expect(fetchCalls).toHaveLength(1)
    expect(fetchCalls[0]).toContain('/api/stt?customer_id=CUST00860&language=en')
    expect(asked).toEqual(['How much did I spend?'])
    expect(session.getSnapshot()).toMatchObject({ phase: 'thinking', heard: 'How much did I spend?' })

    // The answer streams, then is done: it is read aloud, the voice fetched ahead first (one TTS request).
    session.setTurns([doneTurn(1), { kind: 'ask', id: 2, question: 'q', answer: EMPTY_ANSWER }])
    expect(speech.state.calls).toHaveLength(0)
    session.setTurns([doneTurn(1), doneTurn(2)])
    const remote = { customerId: 'CUST00860', answerId: 'ans_7', language: 'en' }
    expect(speech.state.prefetched).toEqual([remote])
    expect(speech.state.calls).toEqual([{ id: '2', text: 'You spent €42.', voice, remote }])
    expect(session.getSnapshot().phase).toBe('speaking')
    const roundsBefore = recorders.length

    // Nothing is recorded while Sentti speaks; when the voice ends, a new round starts.
    await vi.advanceTimersByTimeAsync(3000)
    expect(recorders).toHaveLength(roundsBefore)
    speech.state.speaking = null
    speech.notify()
    expect(session.getSnapshot().phase).toBe('listening')
    expect(recorders).toHaveLength(roundsBefore + 1)
    expect(closed).toEqual([])
  })

  it("never shows the previous question during a new turn: cleared when listening starts and while the new clip is turned into text", async () => {
    let reply: (value: unknown) => void = () => {}
    const { session } = await open()
    await sayAQuestion()
    expect(session.getSnapshot().heard).toBe('How much did I spend?')
    session.setTurns([doneTurn(1)])
    speech.state.speaking = null
    speech.notify() // the voice ended: a new round
    expect(session.getSnapshot()).toMatchObject({ phase: 'listening', heard: '' })
    // The second clip: while /api/stt works, nothing of the first question shows; the new words come at once.
    sttReply = () => new Promise((resolve) => (reply = resolve))
    await sayAQuestion()
    expect(session.getSnapshot()).toMatchObject({ phase: 'thinking', heard: '' })
    reply({ status: 200, ok: true, json: () => Promise.resolve({ text: 'And last month?' }) })
    await vi.advanceTimersByTimeAsync(10)
    expect(session.getSnapshot()).toMatchObject({ phase: 'thinking', heard: 'And last month?' })
  })

  it('a tap while speaking interrupts and listens again; ✕ stops the voice and releases the microphone', async () => {
    const { session, closed } = await open()
    await sayAQuestion()
    session.setTurns([doneTurn(1)])
    expect(session.getSnapshot().phase).toBe('speaking')
    session.tap()
    expect(speech.state.stops).toBe(1)
    expect(session.getSnapshot().phase).toBe('listening')
    session.exit()
    expect(tracks.stopped).toBe(1)
    expect(closed).toEqual(['exit'])
    expect(recorders.at(-1)?.state).toBe('inactive')
  })

  it('silence costs nothing: it keeps listening without a tap, sends nothing, and closes after a minute (#895)', async () => {
    const { session, closed } = await open()
    await vi.advanceTimersByTimeAsync(15_100)
    expect(fetchCalls).toHaveLength(0)
    expect(session.getSnapshot()).toMatchObject({ phase: 'listening', missed: false, micOn: true })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(closed).toEqual([])
    await vi.advanceTimersByTimeAsync(16_000)
    expect(fetchCalls).toHaveLength(0)
    expect(closed).toEqual([{ kind: 'nothing' }])
    expect(tracks.stopped).toBe(1)
    expect(session.getSnapshot().micOn).toBe(false)
  })

  it('an empty transcript says "Didn\'t catch that"; three in a row close the mode', async () => {
    sttReply = () => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ text: '', empty: true }) })
    const { session, asked, closed } = await open()
    await sayAQuestion()
    expect(asked).toEqual([])
    expect(session.getSnapshot()).toMatchObject({ phase: 'listening', missed: true })
    await sayAQuestion()
    expect(closed).toEqual([])
    await sayAQuestion()
    expect(closed).toEqual([{ kind: 'nothing' }])
  })

  it('opens the microphone with echo cancellation, noise suppression and gain control', async () => {
    const asked: unknown[] = []
    micReply = (constraints?: unknown) => {
      asked.push(constraints)
      return Promise.resolve(micStream(true))
    }
    const { session } = await open()
    expect(asked).toEqual([{ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }])
    expect(session.getSnapshot().bargeIn).toBe(true)
  })

  it('barge-in: speaking over Sentti stops the voice at once and the new turn counts, no tap (#895)', async () => {
    const { session, asked } = await open()
    await sayAQuestion()
    session.setTurns([doneTurn(1)])
    expect(session.getSnapshot().phase).toBe('speaking')
    const rounds = recorders.length
    await vi.advanceTimersByTimeAsync(700) // past the first moment of playback, Sentti still speaking
    loud = true
    await vi.advanceTimersByTimeAsync(400) // the user speaks over it
    expect(speech.state.stops).toBe(1)
    expect(session.getSnapshot().phase).toBe('listening')
    expect(recorders).toHaveLength(rounds + 1)
    loud = false
    await vi.advanceTimersByTimeAsync(1400) // the new turn ends after its silence and is sent
    expect(asked).toHaveLength(2)
  })

  it("no barge-in without echo cancellation: Sentti's own voice never becomes a turn; a tap interrupts", async () => {
    micReply = () => Promise.resolve(micStream(false))
    const { session } = await open()
    expect(session.getSnapshot().bargeIn).toBe(false)
    await sayAQuestion()
    session.setTurns([doneTurn(1)])
    await vi.advanceTimersByTimeAsync(700)
    loud = true // its own voice leaking into the microphone
    await vi.advanceTimersByTimeAsync(2000)
    expect(speech.state.stops).toBe(0)
    expect(session.getSnapshot().phase).toBe('speaking')
    loud = false
  })

  it('a tap while listening sends what was said at once', async () => {
    const { session, asked } = await open()
    loud = true
    await vi.advanceTimersByTimeAsync(700) // over the 0.5 s a clip needs to be sent at all
    session.tap()
    await vi.advanceTimersByTimeAsync(100)
    expect(asked).toEqual(['How much did I spend?'])
  })

  it('a refused microphone or a failed transcription closes the mode with the reason', async () => {
    micReply = () => Promise.reject(Object.assign(new Error('no'), { name: 'NotAllowedError' }))
    const denied = await open()
    expect(denied.closed).toEqual([{ kind: 'mic', failure: 'denied' }])

    micReply = () => Promise.resolve(micStream(true))
    sttReply = () => Promise.resolve({ status: 429, ok: false, json: () => Promise.resolve({}) })
    const busy = await open()
    await sayAQuestion()
    expect(busy.closed).toEqual([{ kind: 'stt', failure: 'busy' }])
  })

  it('an answer that fails closes the mode; with the voice budget low the device voice reads the answer', async () => {
    const failing = await open()
    await sayAQuestion()
    failing.session.setTurns([doneTurn(1, { status: 'error', done: null })])
    expect(failing.closed).toEqual([{ kind: 'answer' }])

    speech.state.budgetLow = true
    const low = await open()
    await sayAQuestion()
    low.session.setTurns([doneTurn(1)])
    expect(speech.state.prefetched).toEqual([])
    expect(speech.state.calls.at(-1)).toMatchObject({ id: '1', voice, remote: null })
  })
})
