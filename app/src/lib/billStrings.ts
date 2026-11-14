// The bill flow's own strings (DESIGN.md section 6: short, friendly, no blame). Everything the
// API sends (field displays, notes, sentences, error messages) is shown as received.
import type { Language } from '../api/types.ts'

const en = {
  galleryTitle: 'Pick a sample bill',
  galleryHint: 'Sentti reads the bill, then you check what it found.',
  sampleLanguage: { en: 'Bill in English', fi: 'Bill in Finnish' } as Record<Language, string>,
  reading: 'Reading the bill…',
  backToSamples: 'Back to samples',
  confirmTitle: 'I read your bill. Is this right?',
  cardTitle: 'Bill details',
  cardSubtitle: 'Read from the bill · check before you continue',
  checkedMeans: 'Checked means the code verified it from the barcode or a check digit. Fields you haven’t confirmed are never used.',
  looksRight: 'Looks right, explain it',
  editDetails: 'Edit details',
  typeTitle: 'Type the bill’s details',
  checked: 'Checked',
  isThisRight: 'Is this right?',
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
  confirm: 'Confirm',
  barcodeKept: 'If you change the account, reference, amount or due date, Sentti uses your typed details instead of the barcode.',
  amountHint: 'For example 145.00',
  problems: {
    required: 'Fill this in.',
    too_long: 'This is longer than a bill allows. Check it against the bill.',
    amount_format: 'Write the amount in euros, with at most two decimals, for example 145.00.',
    amount_range: 'The amount must be more than €0 and at most €100,000.',
    date_format: 'Pick the due date.',
  },
  noCustomer: 'Pick a demo persona first.',
}

type BillStrings = typeof en

const fi: BillStrings = {
  galleryTitle: 'Valitse esimerkkilasku',
  galleryHint: 'Sentti lukee laskun, ja sinä tarkistat, mitä se löysi.',
  sampleLanguage: { en: 'Englanninkielinen lasku', fi: 'Suomenkielinen lasku' },
  reading: 'Luetaan laskua…',
  backToSamples: 'Takaisin esimerkkeihin',
  confirmTitle: 'Luin laskusi. Onko tämä oikein?',
  cardTitle: 'Laskun tiedot',
  cardSubtitle: 'Luettu laskusta · tarkista ennen kuin jatkat',
  checkedMeans: 'Tarkistettu tarkoittaa, että koodi on varmistanut tiedon viivakoodista tai tarkisteesta. Tietoja, joita et ole vahvistanut, ei koskaan käytetä.',
  looksRight: 'Näyttää oikealta, selitä',
  editDetails: 'Muokkaa tietoja',
  typeTitle: 'Kirjoita laskun tiedot',
  checked: 'Tarkistettu',
  isThisRight: 'Onko tämä oikein?',
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
  confirm: 'Vahvista',
  barcodeKept: 'Jos muutat tilinumeroa, viitenumeroa, summaa tai eräpäivää, Sentti käyttää kirjoittamiasi tietoja viivakoodin sijaan.',
  amountHint: 'Esimerkiksi 145,00',
  problems: {
    required: 'Täytä tämä kenttä.',
    too_long: 'Tämä on pidempi kuin laskussa voi olla. Tarkista se laskusta.',
    amount_format: 'Kirjoita summa euroina, enintään kahdella desimaalilla, esimerkiksi 145,00.',
    amount_range: 'Summan pitää olla yli 0 ja enintään 100 000 €.',
    date_format: 'Valitse eräpäivä.',
  },
  noCustomer: 'Valitse ensin demohenkilö.',
}

export function billStrings(lang: Language): BillStrings {
  return lang === 'fi' ? fi : en
}
