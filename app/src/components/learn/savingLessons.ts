import type { Language, OverviewResponse } from '../../api/types.ts'
import { lessonTwo, type QuizLesson } from '../lesson/lessons.ts'

// The "Saving and a buffer" topic (#764 step 3): two lessons on saving first and the reserve for
// must-have surprises. The examples quote the customer's own figures as the API's `display`; without
// the figure the example is left out. Own short texts; no products, funds, shares or loans.

export function savingLessons(overview: OverviewResponse | null, lang: Language): QuizLesson[] {
  const save = overview?.safe_to_save?.monthly.display ?? null
  const reserve = lessonTwo(overview)?.rows.find((row) => row.key === 'unexpected_necessities')?.display ?? null
  const fi = lang === 'fi'
  return [
    {
      kind: 'quiz',
      key: 'saving-1',
      question: fi ? 'Milloin säästäminen onnistuu helpoimmin?' : 'When is saving easiest?',
      options: fi
        ? [
            { key: 'payday', text: 'Heti palkkapäivänä, automaattisesti' },
            { key: 'end', text: 'Kuun lopussa, jos jotain jää' },
            { key: 'big', text: 'Vain isoa hankintaa varten' },
          ]
        : [
            { key: 'payday', text: 'Right after payday, automatically' },
            { key: 'end', text: 'At the end of the month, if anything is left' },
            { key: 'big', text: 'Only before a big purchase' },
          ],
      right: 'payday',
      reveal: fi
        ? 'Kun säästö siirtyy heti palkkapäivänä, se tapahtuu ennen kuluttamista.'
        : 'Moving the saving on payday means it happens before the spending does.',
      example: save
        ? fi
          ? `Sentin mukaan voit tavallisesti säästää ${save}.`
          : `Sentti says you can typically put aside ${save}.`
        : null,
      concept: fi
        ? 'Maksa ensin itsellesi: automaattinen siirto palkkapäivänä tekee säästämisestä tavan.'
        : 'Pay yourself first: an automatic transfer on payday makes saving a habit.',
    },
    {
      kind: 'quiz',
      key: 'saving-2',
      question: fi
        ? 'Yllättävä 300 euron hammaslääkärilasku tulee. Mikä pitää kuukauden raiteillaan?'
        : 'A surprise €300 dentist bill arrives. What keeps your month on track?',
      options: fi
        ? [
            { key: 'buffer', text: 'Sivuun pantu puskuri' },
            { key: 'late', text: 'Laskun maksaminen myöhässä' },
            { key: 'food', text: 'Ruokaostoksista tinkiminen' },
          ]
        : [
            { key: 'buffer', text: 'A buffer kept aside' },
            { key: 'late', text: 'Paying the bill late' },
            { key: 'food', text: 'Cutting back on groceries' },
          ],
      right: 'buffer',
      reveal: fi ? 'Puskuri tekee yllätyksestä suunnitelman.' : 'A buffer turns a surprise into a plan.',
      example: reserve
        ? fi
          ? `Epäsäännölliset välttämättömät menosi: ${reserve}. Sentti pitää niitä varten varausta käyttövarassasi.`
          : `Your irregular must-haves: ${reserve}. Sentti keeps a reserve for them in your left to spend.`
        : null,
      concept: fi
        ? 'Moni aloittaa puskurista, joka kattaa noin kuukauden välttämättömät menot, ja kasvattaa sitä vähitellen.'
        : 'Many start with a buffer of about a month of essential costs and build it up over time.',
    },
  ]
}
