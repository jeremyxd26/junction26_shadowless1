// Voice mode's own strings (#811), kept out of i18n.ts like micStrings.ts.
import type { Language } from '../api/types.ts'

interface VoiceModeStrings {
  /** The send button's name while the input is empty. */
  start: string
  /** The overlay's name, the exit button and the wave button in each phase. */
  title: string
  exit: string
  sendNow: string
  interrupt: string
  /** The caption under the wave. */
  listening: string
  thinking: string
  speaking: string
  /** Under the caption after a round in which no words were heard. */
  missed: string
  /** The End button, the open-microphone line, and how to interrupt while Sentti speaks (#895). */
  end: string
  micOn: string
  speakToInterrupt: string
  tapToInterrupt: string
  /** The toast when voice mode closes by itself. */
  nothing: string
  answerFailed: string
}

const STRINGS: Record<Language, VoiceModeStrings> = {
  en: {
    start: 'Start voice mode',
    title: 'Voice mode',
    exit: 'Exit voice mode',
    sendNow: 'Done talking, send now',
    interrupt: 'Interrupt Sentti',
    listening: 'Listening…',
    thinking: 'Thinking…',
    speaking: 'Speaking…',
    missed: "Didn't catch that. Try again.",
    end: 'End voice mode',
    micOn: 'Microphone on',
    speakToInterrupt: 'Speak to interrupt',
    tapToInterrupt: 'Tap the wave to interrupt',
    nothing: "Voice mode closed: I didn't hear anything for a while. You can type your question instead.",
    answerFailed: 'Something went wrong with the answer. You can type your question instead.',
  },
  fi: {
    start: 'Aloita puhetila',
    title: 'Puhetila',
    exit: 'Lopeta puhetila',
    sendNow: 'Valmis, lähetä nyt',
    interrupt: 'Keskeytä Sentti',
    listening: 'Kuuntelen…',
    thinking: 'Mietin…',
    speaking: 'Puhun…',
    missed: 'En saanut selvää. Yritä uudelleen.',
    end: 'Lopeta puhetila',
    micOn: 'Mikrofoni päällä',
    speakToInterrupt: 'Puhu, niin keskeytän',
    tapToInterrupt: 'Napauta aaltoa keskeyttääksesi',
    nothing: 'Puhetila suljettiin: en kuullut mitään vähään aikaan. Voit kirjoittaa kysymyksesi.',
    answerFailed: 'Vastauksessa meni jokin vikaan. Voit kirjoittaa kysymyksesi.',
  },
}

export function voiceModeStrings(lang: Language): VoiceModeStrings {
  return STRINGS[lang]
}
