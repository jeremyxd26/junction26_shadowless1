import type { Language } from '../api/types.ts'
import { chatStrings } from '../lib/chatStrings.ts'
import { clientTurnRequest, clientTurns, openingChips } from './clientTurns.tsx'

/** Every question the opening's "More questions" sheet lists: the first ones, the client chips, then the rest. */
export function chipTexts(lang: Language): string[] {
  const s = chatStrings(lang)
  const client = openingChips.filter((key) => clientTurns[key]?.visible()).map((key) => clientTurnRequest(key, lang).question)
  return [...s.openingFirst, ...client, ...s.openingMore]
}
