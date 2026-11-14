// Reading an answer aloud (#252) with the browser's own speechSynthesis: on the device only,
// nothing is sent anywhere and nothing is stored. One answer speaks at a time; starting another
// stops the first. The text is the answer's `text_rendered` exactly as the API sent it.
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

/** The best installed voice for `lang`, or null when the device has none (the button is then hidden). */
export function voiceFor(voices: readonly SpeechSynthesisVoice[], lang: Language): SpeechSynthesisVoice | null {
  for (const wanted of SPOKEN[lang]) {
    const exact = voices.find((voice) => voice.lang.toLowerCase().replace('_', '-') === wanted.toLowerCase())
    if (exact) return exact
  }
  const prefix = SPOKEN[lang][SPOKEN[lang].length - 1].toLowerCase()
  return voices.find((voice) => voice.lang.toLowerCase().startsWith(prefix)) ?? null
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

// Which answer is speaking now (its turn id), shared by every button.
let speakingId: string | null = null
const speakingListeners = new Set<() => void>()

function setSpeaking(id: string | null) {
  speakingId = id
  for (const listener of speakingListeners) listener()
}

function subscribeSpeaking(onChange: () => void) {
  speakingListeners.add(onChange)
  return () => speakingListeners.delete(onChange)
}

export function useSpeakingId(): string | null {
  return useSyncExternalStore(subscribeSpeaking, () => speakingId, () => speakingId)
}

/** Speaks `text` for the answer `id`, stopping whatever was speaking. */
export function speak(id: string, text: string, voice: SpeechSynthesisVoice) {
  const s = synth()
  if (!s) return
  s.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.voice = voice
  utterance.lang = voice.lang
  const finish = () => {
    if (speakingId === id) setSpeaking(null)
  }
  utterance.onend = finish
  utterance.onerror = finish
  setSpeaking(id)
  s.speak(utterance)
}

/** Stops speech; with `id`, only when that answer is the one speaking. */
export function stopSpeaking(id?: string) {
  if (id !== undefined && speakingId !== id) return
  synth()?.cancel()
  setSpeaking(null)
}
