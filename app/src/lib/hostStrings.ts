// Strings for hand-overs to the host app (DESIGN.md section 6: short, friendly).
import type { Language } from '../api/types.ts'

const en = {
  continuesInBankApp: 'This continues in the bank app.',
}

type HostStrings = typeof en

const fi: HostStrings = {
  continuesInBankApp: 'Tämä jatkuu pankin sovelluksessa.',
}

export function hostStrings(lang: Language): HostStrings {
  return lang === 'fi' ? fi : en
}
