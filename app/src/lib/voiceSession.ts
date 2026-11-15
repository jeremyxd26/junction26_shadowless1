// One voice-mode conversation (#811): listen, turn the words into a question, wait for the answer, read it
// aloud, listen again. It lives outside React, so its timers, the microphone and the requests follow one
// state machine; the overlay (components/VoiceMode.tsx) subscribes to its snapshot. What is sent, and when,
// is in voiceMode.ts.
import type { Language } from '../api/types.ts'
import {
  TTS_LIVE,
  prefetchVoice,
  readOutput,
  speakAnswer,
  speakingNow,
  stopSpeaking,
  subscribeSpeaking,
  voiceBudgetLow,
} from './speech.ts'
import {
  AUDIO_BITS_PER_SECOND,
  STT_TIMEOUT_MS,
  SttFailed,
  clipTooShort,
  levelOf,
  micFailure,
  pickType,
  transcribe,
  type SttFailure,
} from './stt.ts'
import type { Turn } from './thread.ts'
import {
  LISTEN_MS,
  MAX_EMPTY_ROUNDS,
  SILENT_CLOSE_MS,
  bargeDetector,
  endpointer,
  followAnswer,
  waveBars,
  type Endpointer,
} from './voiceMode.ts'

export type VoicePhase = 'starting' | 'listening' | 'thinking' | 'speaking'

export interface VoiceSnapshot {
  phase: VoicePhase
  /** The last round heard no words: "Didn't catch that". */
  missed: boolean
  /** The words of the question being answered, once they are known. */
  heard: string
  /** The microphone is open (the overlay shows it); it stays open for the whole session. */
  micOn: boolean
  /** Speaking over Sentti interrupts it (the browser cancels its echo); else a tap on the wave does (#895). */
  bargeIn: boolean
}

/** Why the session ended by itself; the chat shows it as a toast. An exit by the user has no reason. */
export type VoiceEnd = { kind: 'mic' | 'stt'; failure: SttFailure } | { kind: 'nothing' } | { kind: 'answer' }

export interface VoiceDeps {
  customerId: string
  lang: Language
  /** Sends the words as a question in the thread, as the composer's send does. */
  ask(question: string): void
  /** Called once when the session ends, with the reason when it ended by itself. */
  closed(reason?: VoiceEnd): void
}

/** How often a listening round reads the level (also in a background tab, where frames stop). */
const TICK_MS = 50
/** An answer that has not finished by then ends the mode (a stream that never says done). */
const ANSWER_MS = 90_000

interface Mic {
  stream: MediaStream
  analyser: AnalyserNode | null
  time: Uint8Array<ArrayBuffer>
  freq: Uint8Array<ArrayBuffer>
}

interface Round {
  recorder: MediaRecorder
  chunks: Blob[]
  ends: Endpointer
  started: number
  ticker: number
  stopping: boolean
  /** Ended by a tap ("done talking"): sent even when the meter heard nothing. */
  forced: boolean
  cancelled: boolean
}

function stopTracks(stream: MediaStream) {
  for (const track of stream.getTracks()) track.stop()
}

export class VoiceSession {
  private snapshot: VoiceSnapshot = { phase: 'starting', missed: false, heard: '', micOn: false, bargeIn: false }
  private readonly listeners = new Set<() => void>()
  private readonly deps: VoiceDeps
  private readonly context: AudioContext | null
  private turns: Turn[]
  private voice: SpeechSynthesisVoice | null = null
  private mic: Mic | null = null
  private round: Round | null = null
  private request: AbortController | null = null
  private empty = 0
  /** The last turn id when the question was sent: its answer is the next ask turn. */
  private askedAfter: number | null = null
  private watchdog = 0
  /** The turn id being read aloud. */
  private speaking: string | null = null
  private readonly outFreq = new Uint8Array(64)
  private ended = false
  private releaseTimer = 0
  /** When speech was last heard: a long silence closes the mode (no background listening). */
  private lastHeardAt = Date.now()
  /** While Sentti speaks: the meter watching for the user's voice (barge-in, #895). */
  private barge = 0
  /** The next round starts with speech already going (the user spoke over Sentti). */
  private bargedIn = false
  private readonly unsubscribe: () => void
  private readonly onHidden = () => {
    if (document.hidden) this.end()
  }

  /** `context` is made in the tap that opens the mode (iOS lets only such a context run); the session closes it. */
  constructor(deps: VoiceDeps, context: AudioContext | null, turns: Turn[]) {
    this.deps = deps
    this.context = context
    this.turns = turns
    this.unsubscribe = subscribeSpeaking(() => this.speechChanged())
  }

  readonly subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  readonly getSnapshot = () => this.snapshot

  private set(change: Partial<VoiceSnapshot>) {
    this.snapshot = { ...this.snapshot, ...change }
    for (const listener of this.listeners) listener()
  }

  /** Opens the microphone (call it in the tap) and starts the first round. */
  async start() {
    document.addEventListener('visibilitychange', this.onHidden)
    let stream: MediaStream
    try {
      // The browser's own echo cancellation, noise suppression and gain control: Sentti's voice from a speaker
      // must not come back as the user's words (#895).
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    } catch (error) {
      this.end({ kind: 'mic', failure: micFailure(error) })
      return
    }
    if (this.ended) {
      stopTracks(stream)
      return
    }
    let analyser: AnalyserNode | null = null
    if (this.context) {
      try {
        analyser = this.context.createAnalyser()
        analyser.fftSize = 512
        analyser.smoothingTimeConstant = 0.6
        this.context.createMediaStreamSource(stream).connect(analyser)
        void this.context.resume().catch(() => {})
      } catch {
        analyser = null
      }
    }
    this.mic = { stream, analyser, time: new Uint8Array(512), freq: new Uint8Array(256) }
    // Barge-in needs the meter and the browser's echo cancellation; without them a tap on the wave interrupts.
    const settings = stream.getAudioTracks?.()[0]?.getSettings?.()
    this.lastHeardAt = Date.now()
    this.set({ micOn: true, bargeIn: analyser !== null && settings?.echoCancellation !== false })
    this.listen()
  }

  /** The current thread; the answer to the question sent is followed through it. */
  setTurns(turns: Turn[]) {
    this.turns = turns
    this.follow()
  }

  /** The device voice for the app language (the fallback, and the voice when the TTS budget is low). */
  setVoice(voice: SpeechSynthesisVoice | null) {
    this.voice = voice
  }

  /** A tap on the wave: while listening, "done talking"; while speaking, interrupts and listens again. */
  tap() {
    const { phase } = this.snapshot
    if (phase === 'listening' && this.round) {
      this.round.forced = true
      this.stopRound(this.round)
    } else if (phase === 'speaking') {
      stopSpeaking()
    }
  }

  /** The ✕, Esc: ends the session without a message. */
  exit() {
    this.end()
  }

  /** The overlay mounted (again: React's strict mode unmounts and mounts once in development). */
  attach() {
    window.clearTimeout(this.releaseTimer)
  }

  /** The overlay unmounted: the session ends unless it mounts again at once. */
  detach() {
    window.clearTimeout(this.releaseTimer)
    this.releaseTimer = window.setTimeout(() => this.end(), 0)
  }

  /** The wave's bar heights now (0 to 1), or null when there is nothing live to show (thinking, the device voice). */
  wave(count: number): number[] | null {
    const { phase } = this.snapshot
    if (phase === 'listening' && this.mic?.analyser) {
      this.mic.analyser.getByteFrequencyData(this.mic.freq)
      return waveBars(this.mic.freq, count)
    }
    if (phase === 'speaking' && readOutput(this.outFreq)) return waveBars(this.outFreq, count)
    return null
  }

  /** How loud the microphone (listening) or the Gemini voice (speaking) is now, 0 to 1; the reduced-motion ring. */
  level(): number {
    const bars = this.wave(9)
    return bars ? Math.max(...bars) : 0
  }

  private listen() {
    if (this.ended || !this.mic) return
    const type = pickType((candidate) => MediaRecorder.isTypeSupported(candidate))
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(this.mic.stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: AUDIO_BITS_PER_SECOND })
    } catch {
      this.end({ kind: 'mic', failure: 'no_mic' })
      return
    }
    const started = Date.now()
    const barged = this.bargedIn
    this.bargedIn = false
    const round: Round = {
      recorder,
      chunks: [],
      ends: endpointer(started, { heard: barged }),
      started,
      ticker: 0,
      stopping: false,
      forced: false,
      cancelled: false,
    }
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) round.chunks.push(event.data)
    }
    recorder.onstop = () => this.finished(round, recorder.mimeType || type || 'audio/webm')
    try {
      recorder.start()
    } catch {
      this.end({ kind: 'mic', failure: 'no_mic' })
      return
    }
    this.round = round
    round.ticker = window.setInterval(() => this.tick(round), TICK_MS)
    // A new round shows nothing of the turn before: the last question's words go at once.
    this.set({ phase: 'listening', heard: '' })
    if (!barged) this.chime()
  }

  /** A short, soft tone as listening starts (no voice fillers), when the audio context runs. */
  private chime() {
    const ctx = this.context
    if (!ctx || ctx.state !== 'running') return
    try {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = 660
      const now = ctx.currentTime
      gain.gain.setValueAtTime(0, now)
      gain.gain.linearRampToValueAtTime(0.04, now + 0.02)
      gain.gain.linearRampToValueAtTime(0, now + 0.12)
      osc.connect(gain).connect(ctx.destination)
      osc.start(now)
      osc.stop(now + 0.13)
    } catch {
      // no tone, nothing else changes
    }
  }

  private tick(round: Round) {
    if (this.round !== round || round.stopping) return
    const analyser = this.mic?.analyser
    const now = Date.now()
    let state
    if (analyser && this.mic) {
      analyser.getByteTimeDomainData(this.mic.time)
      state = round.ends.push(levelOf(this.mic.time), now)
    } else {
      // No meter: the round runs to the time limit or a tap.
      state = now - round.started >= LISTEN_MS ? 'end' : 'waiting'
    }
    if (state === 'end' || state === 'nothing') this.stopRound(round)
  }

  private stopRound(round: Round) {
    if (round.stopping) return
    round.stopping = true
    window.clearInterval(round.ticker)
    try {
      round.recorder.stop() // onstop goes on with the clip
    } catch {
      this.finished(round, round.recorder.mimeType || 'audio/webm')
    }
  }

  private finished(round: Round, type: string) {
    if (this.round !== round) return
    this.round = null
    window.clearInterval(round.ticker)
    if (round.cancelled || this.ended) return
    const heard = round.forced || !this.mic?.analyser || round.ends.heard()
    const clip = new Blob(round.chunks, { type })
    if (!heard) {
      // Nobody spoke: nothing is sent and nothing is spent, so listening goes on, until a long silence.
      if (Date.now() - this.lastHeardAt >= SILENT_CLOSE_MS) this.end({ kind: 'nothing' })
      else this.listen()
      return
    }
    this.lastHeardAt = Date.now()
    if (clipTooShort(clip.size, Date.now() - round.started)) {
      this.set({ missed: true })
      this.listen()
      return
    }
    this.transcribe(clip)
  }

  /** A transcription with no words: "Didn't catch that" and listen again, or end after MAX_EMPTY_ROUNDS in a row. */
  private miss() {
    this.empty += 1
    if (this.empty >= MAX_EMPTY_ROUNDS) {
      this.end({ kind: 'nothing' })
      return
    }
    this.set({ missed: true })
    this.listen()
  }

  private transcribe(clip: Blob) {
    this.set({ phase: 'thinking', missed: false, heard: '' })
    const controller = new AbortController()
    this.request = controller
    const timer = window.setTimeout(() => controller.abort(), STT_TIMEOUT_MS)
    transcribe(clip, this.deps.customerId, this.deps.lang, controller.signal)
      .then((text) => {
        if (this.request !== controller || this.ended) return
        this.request = null
        this.empty = 0
        this.askedAfter = this.turns.reduce((last, turn) => Math.max(last, turn.id), 0)
        this.set({ heard: text })
        window.clearTimeout(this.watchdog)
        this.watchdog = window.setTimeout(() => this.end({ kind: 'answer' }), ANSWER_MS)
        this.deps.ask(text)
      })
      .catch((error: unknown) => {
        if (this.request !== controller || this.ended) return
        this.request = null
        const failure = error instanceof SttFailed ? error.reason : 'unavailable'
        if (failure === 'no_speech') this.miss()
        else this.end({ kind: 'stt', failure })
      })
      .finally(() => window.clearTimeout(timer))
  }

  private follow() {
    if (this.ended || this.askedAfter === null) return
    const followed = followAnswer(this.turns, this.askedAfter)
    if (followed.state === 'waiting') return
    this.askedAfter = null
    window.clearTimeout(this.watchdog)
    if (followed.state === 'failed') this.end({ kind: 'answer' })
    else if (followed.state === 'stopped') this.listen()
    else this.speak(followed.id, followed.text, followed.answerId, followed.language ?? this.deps.lang)
  }

  private speak(turnId: number, text: string, answerId: string | null, language: Language) {
    const voice = this.voice
    // The Gemini voice by the answer's id, or the device voice when the budget is low and the device has one.
    const remote = TTS_LIVE && answerId && !(voiceBudgetLow() && voice) ? { customerId: this.deps.customerId, answerId, language } : null
    if (!text || (!remote && !voice)) {
      this.listen()
      return
    }
    const id = String(turnId)
    // Fetched "ahead" first, so the speaker button's own prefetch of the latest answer finds it: one request.
    if (remote) prefetchVoice(remote)
    speakAnswer(id, text, voice, remote)
    if (speakingNow() !== id) {
      this.listen()
      return
    }
    this.speaking = id
    this.set({ phase: 'speaking' })
    this.watchForBargeIn()
  }

  /**
   * While Sentti speaks the meter keeps reading the microphone: sustained speech above the barge-in level stops the
   * voice at once (its fetch is aborted too) and a new round starts with that speech already going (#895).
   */
  private watchForBargeIn() {
    const analyser = this.mic?.analyser
    if (!analyser || !this.mic || !this.snapshot.bargeIn) return
    const mic = this.mic
    const detector = bargeDetector(Date.now())
    window.clearInterval(this.barge)
    this.barge = window.setInterval(() => {
      if (this.ended || this.speaking === null) return
      analyser.getByteTimeDomainData(mic.time)
      if (!detector.push(levelOf(mic.time), Date.now())) return
      window.clearInterval(this.barge)
      this.bargedIn = true
      this.lastHeardAt = Date.now()
      stopSpeaking()
    }, TICK_MS)
  }

  /** The voice ended or was interrupted: listen again. */
  private speechChanged() {
    if (this.ended || this.speaking === null || speakingNow() === this.speaking) return
    window.clearInterval(this.barge)
    this.speaking = null
    this.listen()
  }

  private end(reason?: VoiceEnd) {
    if (this.ended) return
    this.ended = true
    window.clearTimeout(this.releaseTimer)
    window.clearTimeout(this.watchdog)
    window.clearInterval(this.barge)
    document.removeEventListener('visibilitychange', this.onHidden)
    this.unsubscribe()
    const round = this.round
    this.round = null
    if (round) {
      round.cancelled = true
      window.clearInterval(round.ticker)
      try {
        round.recorder.stop()
      } catch {
        // already stopped
      }
    }
    this.request?.abort()
    this.request = null
    if (this.speaking !== null) stopSpeaking(this.speaking)
    this.speaking = null
    if (this.mic) stopTracks(this.mic.stream)
    this.mic = null
    this.set({ micOn: false })
    void this.context?.close().catch(() => {})
    this.deps.closed(reason)
  }
}
