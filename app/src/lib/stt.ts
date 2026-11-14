// Speaking a question (#735): a tap records at most 15 s with MediaRecorder, the clip goes to POST /api/stt,
// and the core gives back the words as text, which land in the composer; the user taps send. Nothing is
// stored on the device (no file, no blob: URL) and the core stores neither the audio nor the text.
// A live build only: a mock build has no core to send the clip to, so it shows no mic button.
import type { Language } from '../api/types.ts'
import { MAX_QUESTION } from './useChat.ts'

export const STT_LIVE = import.meta.env.VITE_API_MODE === 'live'
const STT_BASE: string = import.meta.env.VITE_API_BASE ?? ''
/** Recording stops by itself after this long; the core refuses longer WAV clips and anything over 1 MB. */
export const MAX_RECORD_MS = 15_000
/** A cold model request can take a while; the composer stays usable meanwhile. */
export const STT_TIMEOUT_MS = 20_000
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

/** Sends the clip and returns the words. Throws SttFailed: busy (429), too_long (413), no_speech (400, or no
 * words heard), else unavailable (503, a network error, a timeout). */
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
  let data: { text?: unknown }
  try {
    data = (await response.json()) as { text?: unknown }
  } catch {
    throw new SttFailed('unavailable')
  }
  const text = typeof data.text === 'string' ? data.text.trim() : ''
  if (!text) throw new SttFailed('no_speech')
  return text
}

/** The draft with the spoken words added after what is already typed, within the composer's limit. */
export function withSpoken(draft: string, spoken: string): string {
  const before = draft.trim()
  const joined = before ? `${before} ${spoken.trim()}` : spoken.trim()
  return joined.slice(0, MAX_QUESTION)
}
