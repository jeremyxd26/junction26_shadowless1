// "Lesson of the day" (#703, #704): the client turn's texts. Numbers are never written here: every
// amount or share is the API's `display`, passed in. The Finnish rows are listed in the PRs for a
// native check (#555).
import type { Language } from '../../api/types.ts'

export type Span = 'week' | 'month'

type Sentence = (display: string) => string

const en = {
  chip: 'Lesson of the day',
  progress: (n: number, total: number) => `Lesson ${n} of ${total}`,
  /** The name of the answer buttons' group. */
  answers: 'Your answer',
  next: 'Next lesson',
  done: "That's all for today. Ask me anything below.",
  /** Another option, named by its label. */
  isLabel: (display: string, label: string) => `${display} is ${label}.`,
  none: 'No lesson for this profile today. Ask me anything below.',
  /** Lesson 1: left to spend this week (the safe-to-spend figure). */
  one: {
    question: { week: 'How much can you safely spend this week?', month: 'How much can you safely spend this month?' } satisfies Record<Span, string>,
    right: { week: (display) => `Right: ${display} is what's left to spend this week.`, month: (display) => `Right: ${display} is what's left to spend this month.` } satisfies Record<Span, Sentence>,
    close: { week: (display) => `Close. ${display} is what's left to spend this week.`, month: (display) => `Close. ${display} is what's left to spend this month.` } satisfies Record<Span, Sentence>,
    /** The reveal without a verdict, when there was nothing to choose from. */
    plain: { week: (display) => `${display} is what's left to spend this week.`, month: (display) => `${display} is what's left to spend this month.` } satisfies Record<Span, Sentence>,
    concept: 'Left to spend is the money that stays yours after your regular bills and your saving are taken care of.',
  },
  /** Lesson 2: where the money goes (no right or wrong). */
  two: {
    question: 'Which basket takes the biggest part of your money?',
    reveal: 'Here is how your spending splits:',
    concept:
      'Sentti sorts spending into three baskets: regular essentials you pay every month, unexpected necessities you must pay but cannot plan, and everyday spending you choose.',
  },
  /** Lesson 3: how much can be set aside. */
  three: {
    question: 'How much can you set aside each week?',
    right: ((display) => `Right: ${display} is what you can set aside each week.`) as Sentence,
    close: ((display) => `Close. ${display} is what you can set aside each week.`) as Sentence,
    plain: ((display) => `${display} is what you can set aside each week.`) as Sentence,
    concept: 'Pay yourself first: the saving goes aside first, and everyday spending comes from what is left.',
  },
}

type LessonStrings = typeof en

const fi: LessonStrings = {
  chip: 'Päivän oppitunti',
  progress: (n, total) => `Oppitunti ${n}/${total}`,
  answers: 'Vastauksesi',
  next: 'Seuraava oppitunti',
  done: 'Siinä kaikki tältä päivältä. Kysy minulta mitä tahansa alla.',
  isLabel: (display, label) => `${display} on ${label}.`,
  none: 'Tälle profiilille ei ole tänään oppituntia. Kysy minulta mitä tahansa alla.',
  one: {
    question: { week: 'Paljonko voit turvallisesti käyttää tällä viikolla?', month: 'Paljonko voit turvallisesti käyttää tässä kuussa?' },
    right: { week: (display) => `Oikein: ${display} on käyttövarasi tällä viikolla.`, month: (display) => `Oikein: ${display} on käyttövarasi tässä kuussa.` },
    close: { week: (display) => `Melkein. ${display} on käyttövarasi tällä viikolla.`, month: (display) => `Melkein. ${display} on käyttövarasi tässä kuussa.` },
    plain: { week: (display) => `${display} on käyttövarasi tällä viikolla.`, month: (display) => `${display} on käyttövarasi tässä kuussa.` },
    concept: 'Käyttövara on raha, joka jää sinulle, kun säännölliset laskusi ja säästösi on hoidettu.',
  },
  two: {
    question: 'Mikä kori vie suurimman osan rahoistasi?',
    reveal: 'Näin kulutuksesi jakautuu:',
    concept:
      'Sentti jakaa kulutuksen kolmeen koriin: säännölliset menot, jotka maksat joka kuukausi, odottamattomat välttämättömät menot, jotka on maksettava mutta joita ei voi suunnitella, ja arjen kulutus, josta päätät itse.',
  },
  three: {
    question: 'Paljonko voit laittaa sivuun joka viikko?',
    right: (display) => `Oikein: ${display} on summa, jonka voit laittaa sivuun joka viikko.`,
    close: (display) => `Melkein. ${display} on summa, jonka voit laittaa sivuun joka viikko.`,
    plain: (display) => `${display} on summa, jonka voit laittaa sivuun joka viikko.`,
    concept: 'Maksa ensin itsellesi: säästö siirretään sivuun ensin, ja arjen kulutus tulee siitä, mitä jää.',
  },
}

export function lessonStrings(lang: Language): LessonStrings {
  return lang === 'fi' ? fi : en
}
