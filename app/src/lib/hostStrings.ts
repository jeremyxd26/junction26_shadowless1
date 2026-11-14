// Strings that depend on the host app: hand-overs and the demo-only persona button
// (DESIGN.md section 6: short, friendly).
import type { Language } from '../api/types.ts'

const en = {
  continuesInBankApp: 'This continues in the bank app.',
  /** The header button that opens the demo persona sheet, shown only outside a host app. */
  personas: 'Demo personas',
}

type HostStrings = typeof en

const fi: HostStrings = {
  continuesInBankApp: 'Tämä jatkuu pankin sovelluksessa.',
  personas: 'Demopersoonat',
}

export function hostStrings(lang: Language): HostStrings {
  return lang === 'fi' ? fi : en
}
