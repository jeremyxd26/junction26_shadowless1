// The estimate note's own headings (#504). Everything else in the note comes from the API.
import type { Language } from '../api/types.ts'

const en = {
  basedOn: 'Based on',
  weAssume: 'We assume',
  /** The hero's receipt (Renat's phone test): one plain line, the lines, the result, then the method folded. */
  plain: 'An estimate from your past months.',
  receipt: {
    balance: 'Balance',
    bills: 'Bills before payday',
    essentials: 'Usual essentials',
    reserve: 'Reserve for surprises',
    cushion: 'Small cushion',
  },
  spread: 'Spread over the days to payday, capped by your monthly budget',
  howWeEstimate: 'How we estimate',
}

const fi: typeof en = {
  basedOn: 'Perustuu',
  weAssume: 'Oletamme',
  plain: 'Arvio aiemmista kuukausistasi.',
  receipt: {
    balance: 'Saldo',
    bills: 'Laskut ennen palkkapäivää',
    essentials: 'Tavalliset välttämättömät menot',
    reserve: 'Varaus yllätyksiin',
    cushion: 'Pieni puskuri',
  },
  spread: 'Jaettuna päiville palkkapäivään asti, kuukausibudjetin rajoissa',
  howWeEstimate: 'Näin arvioimme',
}

export function estimateStrings(lang: Language): typeof en {
  return lang === 'fi' ? fi : en
}
