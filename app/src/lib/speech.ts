// Reading an answer aloud (#252, #730). What is sent, and when:
// - A live build, on a tap: the app sends the answer's id, never its text, to the core
//   (POST /api/tts). The core has the model provider (Gemini) synthesize the answer's
//   `text_rendered`, unless that audio is already in the core's cache, which keeps it. The app
//   stores nothing.
// - The fallback, and the only voice of a mock build: the browser's speechSynthesis, with voices
//   that run on the device only, so the text is not sent anywhere. A voice with
//   `localService: false` (Chrome's "Google …" voices, Edge's "… Online (Natural)") sends the text
//   to a cloud service, so it is never picked.
// One answer speaks at a time; starting another stops the first. The text is the answer's
// `text_rendered` exactly as the API sent it.
//
// Gemini voice (#730): in a live build the core reads the answer aloud (POST /api/tts names our own
// answer by its id, never a text) and the WAV plays through the Web Audio API, because the page's CSP
// allows no blob: media. Any error, a wait over TTS_TIMEOUT_MS or no answer id: the device voice.
import { useSyncExternalStore } from 'react'
import type { Language } from '../api/types.ts'

/** The BCP 47 language each app language is spoken in, in order of preference. */
const SPOKEN: Record<Language, string[]> = {
  fi: ['fi-FI', 'fi'],
  en: ['en-GB', 'en-US', 'en'],
}

function synth(): SpeechSynthesis | null {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined'
    ? window.speechSynthesis
    : null
}

/**
 * The best voice on the device for `lang`, or null when the device has none (the button is then
 * hidden). Remote voices are skipped, even when they match the language better than a local one.
 */
export function voiceFor(all: readonly SpeechSynthesisVoice[], lang: Language): SpeechSynthesisVoice | null {
  const local = all.filter((voice) => voice.localService === true)
  for (const wanted of SPOKEN[lang]) {
    const exact = local.find((voice) => voice.lang.toLowerCase().replace('_', '-') === wanted.toLowerCase())
    if (exact) return exact
  }
  const prefix = SPOKEN[lang][SPOKEN[lang].length - 1].toLowerCase()
  return local.find((voice) => voice.lang.toLowerCase().startsWith(prefix)) ?? null
}

// Voices load asynchronously in most browsers; `voiceschanged` tells when they arrive.
let voices: SpeechSynthesisVoice[] = []
const voiceListeners = new Set<() => void>()

function refreshVoices() {
  voices = synth()?.getVoices() ?? []
  for (const listener of voiceListeners) listener()
}

function subscribeVoices(onChange: () => void) {
  const s = synth()
  if (voiceListeners.size === 0 && s) {
    refreshVoices()
    s.addEventListener?.('voiceschanged', refreshVoices)
  }
  voiceListeners.add(onChange)
  return () => {
    voiceListeners.delete(onChange)
    if (voiceListeners.size === 0) s?.removeEventListener?.('voiceschanged', refreshVoices)
  }
}

/** The voice for `lang` on this device, or null (no speech support, or no voice for the language). */
export function useVoice(lang: Language): SpeechSynthesisVoice | null {
  const list = useSyncExternalStore(subscribeVoices, () => voices, () => voices)
  return synth() ? voiceFor(list, lang) : null
}

// Which answer is speaking now (its turn id), shared by every button, and the utterance that
// speaks it: a late `end` or `error` of an utterance that was stopped must not touch the state.
let speakingId: string | null = null
let current: SpeechSynthesisUtterance | null = null
const speakingListeners = new Set<() => void>()

function setSpeaking(id: string | null) {
  speakingId = id
  for (const listener of speakingListeners) listener()
}

/** Calls `onChange` whenever the answer that speaks changes (voice mode listens again when it ends). */
export function subscribeSpeaking(onChange: () => void) {
  speakingListeners.add(onChange)
  return () => speakingListeners.delete(onChange)
}

/** The id of the answer that is speaking now, or null. */
export function speakingNow(): string | null {
  return speakingId
}

export function useSpeakingId(): string | null {
  return useSyncExternalStore(subscribeSpeaking, speakingNow, speakingNow)
}

/** Speaks `text` for the answer `id`, stopping whatever was speaking. */
export function speak(id: string, text: string, voice: SpeechSynthesisVoice) {
  const s = synth()
  if (!s) return
  stopAudio()
  // Cleared first: the cancel may end the previous utterance at once or later, and either way
  // that end belongs to an utterance that no longer speaks.
  current = null
  s.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.voice = voice
  utterance.lang = voice.lang
  const finish = () => {
    if (current !== utterance) return
    current = null
    setSpeaking(null)
  }
  utterance.onend = finish
  utterance.onerror = finish
  current = utterance
  setSpeaking(id)
  s.speak(utterance)
}

/** Stops speech; with `id`, only when that answer is the one speaking. */
export function stopSpeaking(id?: string) {
  if (id !== undefined && speakingId !== id) return
  if (speakingId === null && current === null && pending === null && source === null) return
  current = null
  stopAudio()
  synth()?.cancel()
  setSpeaking(null)
}

/** Live builds fetch the Gemini voice from the core; a mock build keeps the device voice. */
export const TTS_LIVE = import.meta.env.VITE_API_MODE === 'live'
const TTS_BASE: string = import.meta.env.VITE_API_BASE ?? ''
const TTS_TIMEOUT_MS = 8000

// The voice request in flight and the audio that plays: a stop or another answer aborts or stops them,
// and a late response of an aborted request never plays.
let pending: AbortController | null = null
let source: AudioBufferSourceNode | null = null
let audioContext: AudioContext | null = null

// The answer whose voice is being prepared (the request is in flight): its button shows a spinner at once.
let preparingId: string | null = null
const preparingListeners = new Set<() => void>()

function setPreparing(id: string | null) {
  if (preparingId === id) return
  preparingId = id
  for (const listener of preparingListeners) listener()
}

function subscribePreparing(onChange: () => void) {
  preparingListeners.add(onChange)
  return () => preparingListeners.delete(onChange)
}

const preparingNow = () => preparingId

/** The id of the answer whose voice is being prepared, or null. */
export function usePreparingId(): string | null {
  return useSyncExternalStore(subscribePreparing, preparingNow, preparingNow)
}

// The latest answer's voice, fetched ahead once and kept in memory only (one answer), so a tap plays at
// once. The core says `X-Tts-Budget: low` when fewer than 50 voice requests are left (or the budget is
// used up): from then on nothing is fetched ahead, an answer is read only on a tap.
let ahead: { answerId: string; data: Promise<ArrayBuffer> } | null = null
let budgetLow = false

function requestVoice(remote: RemoteAnswer, signal?: AbortSignal): Promise<ArrayBuffer> {
  return fetch(`${TTS_BASE}/api/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'audio/wav' },
    body: JSON.stringify({ customer_id: remote.customerId, answer_id: remote.answerId, language: remote.language }),
    signal,
  }).then((response) => {
    if (response.headers?.get?.('X-Tts-Budget') === 'low' || response.status === 429) budgetLow = true
    if (!response.ok) throw new Error(`tts ${response.status}`)
    return response.arrayBuffer()
  })
}

/** Data saving on (the browser's Save-Data): nothing is fetched ahead. */
function savingData(): boolean {
  return typeof navigator !== 'undefined' && (navigator as { connection?: { saveData?: boolean } }).connection?.saveData === true
}

/** Fetches the latest answer's voice ahead (once), unless the budget is low or data saving is on. */
export function prefetchVoice(remote: RemoteAnswer) {
  if (!TTS_LIVE || budgetLow || savingData()) return
  if (ahead?.answerId === remote.answerId) return
  const data = requestVoice(remote)
  ahead = { answerId: remote.answerId, data }
  data.catch(() => {
    if (ahead?.data === data) ahead = null
  })
}

/** Rejects when `signal` aborts (a stop, another answer, the time limit), so a fetched-ahead voice can lose too. */
function untilAbort(signal: AbortSignal): Promise<never> {
  return new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }))
}

function stopAudio() {
  pending?.abort()
  pending = null
  setPreparing(null)
  const node = source
  source = null
  if (node) {
    try {
      node.stop()
    } catch {
      // already ended
    }
  }
}

function audio(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return null
  audioContext ??= new Ctor()
  return audioContext
}

// Voice mode (#811): the Gemini voice plays through an analyser, so the wave can follow it.
let output: AnalyserNode | null = null

function outputNode(ctx: AudioContext): AudioNode {
  if (output?.context === ctx) return output
  try {
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 128
    analyser.connect(ctx.destination)
    output = analyser
    return analyser
  } catch {
    return ctx.destination
  }
}

/** Voice mode: the frequencies of the Gemini voice playing now, into `frame`; false when none plays. */
export function readOutput(frame: Uint8Array<ArrayBuffer>): boolean {
  if (!output || !source) return false
  output.getByteFrequencyData(frame)
  return true
}

/** Whether the core said the voice budget is low (`X-Tts-Budget: low` or a 429): voice mode then uses the device voice. */
export function voiceBudgetLow(): boolean {
  return budgetLow
}

/**
 * Voice mode reads answers aloud without a tap on each one. Called in the tap that opens it: the audio
 * context is made and resumed inside the gesture, and an empty utterance unlocks the device voice, as iOS
 * Safari requires for any later playback.
 */
export function unlockVoice() {
  if (TTS_LIVE) audio()?.resume().catch(() => {})
  const s = synth()
  if (!s || s.speaking) return
  try {
    const silent = new SpeechSynthesisUtterance('')
    silent.volume = 0
    s.speak(silent)
  } catch {
    // no device voice: the Gemini voice still plays
  }
}

/** The answer the core reads aloud: our own answer by its id (`done.answer_id`) for this customer. */
export interface RemoteAnswer {
  customerId: string
  answerId: string
  language: Language
}

/**
 * Reads the answer `id` aloud: with the Gemini voice from the core when `remote` is given in a live
 * build, else (and on any failure of it) with the device `voice`. Call it from the tap itself: the
 * audio context is resumed inside the gesture, as iOS Safari requires.
 */
export function speakAnswer(id: string, text: string, voice: SpeechSynthesisVoice | null, remote: RemoteAnswer | null) {
  const ctx = TTS_LIVE && remote ? audio() : null
  if (!ctx || !remote) {
    if (voice) speak(id, text, voice)
    return
  }
  stopSpeaking()
  ctx.resume().catch(() => {})
  const controller = new AbortController()
  pending = controller
  setSpeaking(id)
  // The button shows "Preparing the voice…" at once; a voice fetched ahead plays without a wait.
  setPreparing(id)
  const timer = setTimeout(() => controller.abort(), TTS_TIMEOUT_MS)
  const fetched = ahead?.answerId === remote.answerId ? ahead.data : requestVoice(remote, controller.signal)
  Promise.race([fetched, untilAbort(controller.signal)])
    // A copy: decoding detaches the buffer, and the fetched-ahead voice may play again.
    .then((data) => ctx.decodeAudioData(data.slice(0)))
    .then((buffer) => {
      clearTimeout(timer)
      if (pending !== controller) return
      pending = null
      setPreparing(null)
      const node = ctx.createBufferSource()
      node.buffer = buffer
      node.connect(outputNode(ctx))
      node.onended = () => {
        if (source !== node) return
        source = null
        setSpeaking(null)
      }
      source = node
      node.start()
    })
    .catch(() => {
      clearTimeout(timer)
      if (pending !== controller) return
      pending = null
      setPreparing(null)
      if (voice) speak(id, text, voice)
      else setSpeaking(null)
    })
}
