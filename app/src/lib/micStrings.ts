// The composer mic's own strings (#735), kept out of i18n.ts like speechStrings.ts.
import type { Language } from '../api/types.ts'
import type { SttFailure } from './stt.ts'

interface MicStrings {
  /** One name in every state; aria-pressed says whether it is recording. */
  speak: string
  /** The recording bar (#751): its two buttons, and what a screen reader hears while it records. */
  cancel: string
  stop: string
  recording: string
  writing: string
  /** Announced when the words are in the composer. */
  ready: string
  failures: Record<SttFailure, string>
}

const STRINGS: Record<Language, MicStrings> = {
  en: {
    speak: 'Speak your question',
    cancel: 'Cancel recording',
    stop: 'Stop and transcribe',
    recording: 'Recording',
    writing: 'Turning it into text…',
    ready: 'Your question is in the box. Check it and tap send.',
    failures: {
      denied: 'Microphone access is off. You can type your question instead.',
      no_mic: 'No microphone found. You can type your question instead.',
      busy: 'Too many tries just now. Type your question or try again later.',
      too_long: 'That was too long. Speak for 15 seconds at most.',
      no_speech: "I didn't catch that. Try again.",
      unavailable: "Voice input isn't available right now. Please type your question.",
    },
  },
  fi: {
    speak: 'Sano kysymyksesi',
    cancel: 'Peru nauhoitus',
    stop: 'Lopeta ja kirjoita teksti',
    recording: 'Nauhoitetaan',
    writing: 'Muutetaan tekstiksi…',
    ready: 'Kysymyksesi on kentässä. Tarkista se ja paina lähetä.',
    failures: {
      denied: 'Mikrofoni ei ole käytössä. Voit kirjoittaa kysymyksesi.',
      no_mic: 'Mikrofonia ei löytynyt. Voit kirjoittaa kysymyksesi.',
      busy: 'Liian monta yritystä juuri nyt. Kirjoita kysymys tai yritä myöhemmin.',
      too_long: 'Liian pitkä. Puhu enintään 15 sekuntia.',
      no_speech: 'En saanut selvää. Yritä uudelleen.',
      unavailable: 'Puhesyöte ei ole nyt käytettävissä. Kirjoita kysymyksesi.',
    },
  },
}

export function micStrings(lang: Language): MicStrings {
  return STRINGS[lang]
}
