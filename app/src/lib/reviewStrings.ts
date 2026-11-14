// The pointer that a `review` card in an answer shows instead of a second question (#318), and
// the line that says where the purchase went once the opening's question is answered (#452).
// Short by rule (#310): a title of at most 4 words, a caption of at most 8.
import type { Language } from '../api/types.ts'

const en = {
  asked: 'Sentti already asked about this purchase.',
  show: 'Show',
  showLabel: 'Show the question about this purchase',
  /** Followed by the basket's icon and label, then a full stop. */
  putIn: 'You put this in',
}

type ReviewStrings = typeof en

const fi: ReviewStrings = {
  asked: 'Sentti kysyi jo tästä ostoksesta.',
  show: 'Näytä',
  showLabel: 'Näytä kysymys tästä ostoksesta',
  putIn: 'Laitoit tämän koriin',
}

export function reviewStrings(lang: Language): ReviewStrings {
  return lang === 'fi' ? fi : en
}
