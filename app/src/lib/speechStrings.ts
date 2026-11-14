// The speaker button's own strings (#252), kept out of i18n.ts.
import type { Language } from '../api/types.ts'

// One name for the speaker button in both states; `aria-pressed` says whether it is reading (#582).
const STRINGS: Record<Language, { read: string; preparing: string }> = {
  en: { read: 'Read aloud', preparing: 'Preparing the voice…' },
  fi: { read: 'Lue ääneen', preparing: 'Valmistellaan ääntä…' },
}

export function speechStrings(lang: Language) {
  return STRINGS[lang]
}
