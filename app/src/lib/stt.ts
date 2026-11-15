// Speaking a question (#735). What is sent, and when:
// - Only on a tap of the mic (or in voice mode, below): MediaRecorder records at most 15 s of audio (stop sends it
//   sooner, cancel drops it).
// - That clip goes to the core (POST /api/stt, contracts/api.md section 13), and from the core to the model
//   provider (Gemini) for transcription. The core sends back the words as text.
// - No audio is stored: the clip stays in memory for the one request (no file, no blob: URL, no storage),
//   and the core stores neither the audio nor the text. The recording bar's waveform reads only the level.
// - The text lands in the composer. Nothing is sent to the coach until the user taps send, except in voice mode:
//   after the one tap that opens it, it records round after round (never while Sentti speaks) and sends the
//   words as a question without that tap (voiceMode.ts, #811).
// - In the demo frame the iframe needs allow="microphone" (app/src/demo/main.ts).
// A live build only: a mock build has no core to send the clip to, so it shows no mic button.
import type { Language } from '../api/types.ts'
import { MAX_QUESTION } from './useChat.ts'

export const STT_LIVE = import.meta.env.VITE_API_MODE === 'live'
const STT_BASE: string = import.meta.env.VITE_API_BASE ?? ''
/** Recording stops by itself after this long; the core refuses longer WAV clips and anything over 1 MB. */
export const MAX_RECORD_MS = 15_000
/** A cold model request can take a while; the composer stays usable meanwhile. */
export const STT_TIMEOUT_MS = 20_000
/** A shorter recording (a quick double tap) holds no question: it is never sent (#759). */
export const MIN_RECORD_MS = 500
/** Small clips: 15 s of speech at 32 kbit/s is about 60 KB. */
export const AUDIO_BITS_PER_SECOND = 32_000

/** The recording types in order of preference: Chrome and Firefox record WebM/Opus, Safari MP4/AAC. */
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

/** Whether this browser can record from a microphone at all (an insecure page has no mediaDevices). */
export function canRecord(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function'
  )
}

/** The first recording type the browser supports, or '' to let it choose. */
export function pickType(isSupported: (type: string) => boolean): string {
  return (
    TYPES.find((type) => {
      try {
        return isSupported(type)
      } catch {
        return false
      }
    }) ?? ''
  )
}

/** Why a spoken question did not become text; each has its own short message. */
export type SttFailure = 'denied' | 'no_mic' | 'busy' | 'too_long' | 'no_speech' | 'unavailable'

export class SttFailed extends Error {
  readonly reason: SttFailure
  constructor(reason: SttFailure) {
    super(reason)
    this.reason = reason
  }
}

/** A getUserMedia refusal: the user or the page's policy said no (or the iframe has no allow="microphone"). */
export function micFailure(error: unknown): SttFailure {
  const name = error instanceof Error || error instanceof DOMException ? error.name : ''
  return name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError' ? 'denied' : 'no_mic'
}

/** The recording bar's timer (#751): 0:03, 0:15. */
export function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** How loud the microphone is now, 0 to 1, read through a Web Audio AnalyserNode for the recording bar's
 * waveform (#751). Only the level is read: nothing is kept or sent. Null when the browser has no Web Audio. */
export interface LevelMeter {
  read: () => number
  close: () => void
}

/** An AudioContext for the meter, made in the tap itself: a context made after the permission prompt can
 * stay suspended on iOS. Null when the browser has no Web Audio. */
export function audioContext(): AudioContext | null {
  const Context =
    typeof window === 'undefined'
      ? undefined
      : (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
  if (!Context) return null
  try {
    return new Context()
  } catch {
    return null
  }
}

export function levelMeter(context: AudioContext | null, stream: MediaStream): LevelMeter | null {
  if (!context) return null
  const close = () => void context.close().catch(() => {})
  try {
    const analyser = context.createAnalyser()
    analyser.fftSize = 512
    context.createMediaStreamSource(stream).connect(analyser)
    void context.resume().catch(() => {})
    const samples = new Uint8Array(analyser.fftSize)
    return {
      read: () => {
        analyser.getByteTimeDomainData(samples)
        return levelOf(samples)
      },
      close,
    }
  } catch {
    close()
    return null
  }
}

/** The loudness of one frame of 8-bit samples (128 is silence), scaled so speech fills the bar. */
export function levelOf(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) {
    const x = (samples[i] - 128) / 128
    sum += x * x
  }
  return Math.min(1, Math.sqrt(sum / samples.length) * 4)
}

/** Whether a finished recording is empty or too short to hold a question: then it is not sent (#759). */
export function clipTooShort(bytes: number, ms: number): boolean {
  return bytes === 0 || ms < MIN_RECORD_MS
}

/** Sends the clip and returns the words. Throws SttFailed: busy (429), too_long (413), no_speech (400, or a
 * 200 with no words heard: `empty: true` or an empty text, #759), else unavailable (503, a network error, a timeout). */
export async function transcribe(clip: Blob, customerId: string, language: Language, signal?: AbortSignal): Promise<string> {
  const params = new URLSearchParams({ customer_id: customerId, language })
  let response: Response
  try {
    response = await fetch(`${STT_BASE}/api/stt?${params.toString()}`, {
      method: 'POST',
      headers: { 'Content-Type': clip.type || 'audio/webm', Accept: 'application/json' },
      body: clip,
      signal,
    })
  } catch {
    throw new SttFailed('unavailable')
  }
  if (response.status === 429) throw new SttFailed('busy')
  if (response.status === 413) throw new SttFailed('too_long')
  if (response.status === 400) throw new SttFailed('no_speech')
  if (!response.ok) throw new SttFailed('unavailable')
  let data: { text?: unknown; empty?: unknown }
  try {
    data = (await response.json()) as { text?: unknown; empty?: unknown }
  } catch {
    throw new SttFailed('unavailable')
  }
  const text = typeof data.text === 'string' ? data.text.trim() : ''
  if (data.empty === true || !text) throw new SttFailed('no_speech')
  return text
}

/** The draft with the spoken words added after what is already typed, within the composer's limit. */
export function withSpoken(draft: string, spoken: string): string {
  const before = draft.trim()
  const joined = before ? `${before} ${spoken.trim()}` : spoken.trim()
  return joined.slice(0, MAX_QUESTION)
}
