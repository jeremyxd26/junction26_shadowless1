// The speaker button's own strings (#252), kept out of i18n.ts.
import type { Language } from '../api/types.ts'

const STRINGS: Record<Language, { read: string; stop: string }> = {
  en: { read: 'Read aloud', stop: 'Stop reading' },
  fi: { read: 'Lue ääneen', stop: 'Lopeta lukeminen' },
}

export function speechStrings(lang: Language) {
  return STRINGS[lang]
}
