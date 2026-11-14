import type { Language } from '../../api/types.ts'
import type { QuizLesson } from '../lesson/lessons.ts'

// The "Your bills" topic (#764): three short lessons on the fields of a Finnish bill. The examples are
// the rent sample bill's fields (core/bills/samples, synthetic data), quoted as text; nothing is formatted.

const SAMPLE = { iban: 'FI09 1234 5600 0010 01', reference: '104521100', due: '8.10.2026' }

const en: QuizLesson[] = [
  {
    kind: 'quiz',
    key: 'bills-1',
    question: 'What does the reference number (viitenumero) on a bill do?',
    options: [
      { key: 'match', text: 'Tells the payee which bill you paid' },
      { key: 'id', text: 'Proves who you are' },
      { key: 'date', text: 'Sets the due date' },
    ],
    right: 'match',
    reveal: 'The reference number matches your payment to the right bill.',
    example: `On the rent sample bill the reference number is ${SAMPLE.reference}.`,
    concept: 'Copy it exactly. With a wrong one the money arrives, but the payee may not see the bill as paid.',
  },
  {
    kind: 'quiz',
    key: 'bills-2',
    question: 'Which field tells where your money goes?',
    options: [
      { key: 'iban', text: 'The IBAN' },
      { key: 'due', text: 'The due date (eräpäivä)' },
      { key: 'ref', text: 'The reference number' },
    ],
    right: 'iban',
    reveal: "The IBAN is the payee's account number.",
    example: `On the rent sample bill: IBAN ${SAMPLE.iban}, due date ${SAMPLE.due}.`,
    concept: 'A Finnish IBAN starts with FI and has 18 characters. The due date (eräpäivä) is the last day to pay without a reminder fee or late-payment interest.',
  },
  {
    kind: 'quiz',
    key: 'bills-3',
    question: 'You want a bill paid on its due date without approving it each month. Which fits?',
    options: [
      { key: 'direct', text: 'Direct payment (suoramaksu)' },
      { key: 'paper', text: 'A paper bill' },
      { key: 'cash', text: 'Paying at a counter' },
    ],
    right: 'direct',
    reveal: 'With direct payment (suoramaksu) the bank pays the bill from your account on its due date, as agreed.',
    example: null,
    concept: 'An e-invoice (e-lasku) comes straight to your online bank: you check and approve it there, or let the bank pay it automatically. Either way, keep enough on the account for the due date.',
  },
]

const fi: QuizLesson[] = [
  {
    kind: 'quiz',
    key: 'bills-1',
    question: 'Mitä laskun viitenumero tekee?',
    options: [
      { key: 'match', text: 'Kertoo laskuttajalle, minkä laskun maksoit' },
      { key: 'id', text: 'Todistaa henkilöllisyytesi' },
      { key: 'date', text: 'Asettaa eräpäivän' },
    ],
    right: 'match',
    reveal: 'Viitenumero kohdistaa maksusi oikeaan laskuun.',
    example: `Vuokralaskun esimerkissä viitenumero on ${SAMPLE.reference}.`,
    concept: 'Kopioi se tarkasti. Väärällä viitteellä raha menee perille, mutta laskuttaja ei välttämättä näe laskua maksetuksi.',
  },
  {
    kind: 'quiz',
    key: 'bills-2',
    question: 'Mistä kentästä näet, minne rahasi menevät?',
    options: [
      { key: 'iban', text: 'IBAN' },
      { key: 'due', text: 'Eräpäivä' },
      { key: 'ref', text: 'Viitenumero' },
    ],
    right: 'iban',
    reveal: 'IBAN on laskuttajan tilinumero.',
    example: `Vuokralaskun esimerkissä: IBAN ${SAMPLE.iban}, eräpäivä ${SAMPLE.due}.`,
    concept: 'Suomalainen IBAN alkaa kirjaimilla FI ja siinä on 18 merkkiä. Eräpäivä on viimeinen päivä maksaa ilman muistutusmaksua tai viivästyskorkoa.',
  },
  {
    kind: 'quiz',
    key: 'bills-3',
    question: 'Haluat laskun maksetuksi eräpäivänä hyväksymättä sitä joka kuukausi. Mikä sopii?',
    options: [
      { key: 'direct', text: 'Suoramaksu' },
      { key: 'paper', text: 'Paperilasku' },
      { key: 'cash', text: 'Maksu tiskillä' },
    ],
    right: 'direct',
    reveal: 'Suoramaksussa pankki maksaa laskun tililtäsi eräpäivänä sovitusti.',
    example: null,
    concept: 'E-lasku tulee suoraan verkkopankkiisi: tarkistat ja hyväksyt sen siellä, tai annat pankin maksaa sen automaattisesti. Pidä tilillä joka tapauksessa tarpeeksi rahaa eräpäivänä.',
  },
]

export function billLessons(lang: Language): QuizLesson[] {
  return lang === 'fi' ? fi : en
}
