// The bill flow's own strings (DESIGN.md section 6: short, friendly, no blame). Everything the
// API sends (field displays, notes, sentences, error messages) is shown as received.
import type { Language } from '../api/types.ts'

const en = {
  galleryTitle: 'Pick a sample bill',
  galleryHint: 'Sentti reads the bill, then you check what it found.',
  sampleLanguage: { en: 'Bill in English', fi: 'Bill in Finnish' } as Record<Language, string>,
  reading: 'Reading the bill…',
  backToSamples: 'Back to samples',
  confirmTitle: 'Is this what the bill says?',
  typeTitle: 'Type the bill’s details',
  checked: 'Checked',
  isThisRight: 'Is this right?',
  notFound: 'Not found on the bill',
  fieldLabels: {
    payee: 'Payee',
    iban: 'Account (IBAN)',
    reference: 'Reference number',
    amount: 'Amount',
    due_date: 'Due date',
    barcode: 'Virtual barcode',
  },
  explaining: 'Explaining the bill…',
  done: 'Done',
}

type BillStrings = typeof en

const fi: BillStrings = {
  galleryTitle: 'Valitse esimerkkilasku',
  galleryHint: 'Sentti lukee laskun, ja sinä tarkistat, mitä se löysi.',
  sampleLanguage: { en: 'Englanninkielinen lasku', fi: 'Suomenkielinen lasku' },
  reading: 'Luetaan laskua…',
  backToSamples: 'Takaisin esimerkkeihin',
  confirmTitle: 'Lukeeko laskussa näin?',
  typeTitle: 'Kirjoita laskun tiedot',
  checked: 'Tarkistettu',
  isThisRight: 'Onko tämä oikein?',
  notFound: 'Ei löytynyt laskusta',
  fieldLabels: {
    payee: 'Saaja',
    iban: 'Tilinumero (IBAN)',
    reference: 'Viitenumero',
    amount: 'Summa',
    due_date: 'Eräpäivä',
    barcode: 'Virtuaaliviivakoodi',
  },
  explaining: 'Selitetään laskua…',
  done: 'Valmis',
}

export function billStrings(lang: Language): BillStrings {
  return lang === 'fi' ? fi : en
}
