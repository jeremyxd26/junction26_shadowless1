// Sentti's mascot (#798): its states and the text that stands in for its motion. Kept out of the
// component file (like micStrings.ts), so the voice mode (#811) can use the same captions.
import type { Language } from '../../api/types.ts'

/** What the mascot shows. `celebrate` plays its pose once, for about 1.2 s, then rests. */
export type MascotState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'celebrate'

export const MASCOT_STATES: readonly MascotState[] = ['idle', 'listening', 'thinking', 'speaking', 'celebrate']

const LABELS: Record<Language, Record<MascotState, string>> = {
  en: { idle: '', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…', celebrate: '' },
  fi: { idle: '', listening: 'Kuuntelen…', thinking: 'Mietin…', speaking: 'Puhun…', celebrate: '' },
}

/**
 * The state as words: "Listening…", "Thinking…" or "Speaking…" ("Kuuntelen…", "Mietin…", "Puhun…").
 * Empty for `idle` and `celebrate`, which have nothing to say. Under reduced motion the mascot shows
 * this text in place of its motion.
 */
export function mascotStateLabel(state: MascotState, lang: Language): string {
  return LABELS[lang][state]
}
