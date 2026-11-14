// The estimate note's own headings (#504). Everything else in the note comes from the API.
import type { Language } from '../api/types.ts'

const en = { basedOn: 'Based on', weAssume: 'We assume' }

const fi: typeof en = { basedOn: 'Perustuu', weAssume: 'Oletamme' }

export function estimateStrings(lang: Language): typeof en {
  return lang === 'fi' ? fi : en
}
