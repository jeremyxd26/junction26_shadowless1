// "Lesson of the day" (#703): the client turn's texts. Numbers are never written here: every amount
// is the API's `display`, passed in. The Finnish rows are listed in the PR for a native check (#555).
import type { Language } from '../../api/types.ts'

export type Span = 'week' | 'month'

const en = {
  chip: 'Lesson of the day',
  progress: (n: number, total: number) => `Lesson ${n} of ${total}`,
  question: { week: 'How much can you safely spend this week?', month: 'How much can you safely spend this month?' } satisfies Record<Span, string>,
  /** The name of the answer buttons' group. */
  answers: 'Your answer',
  right: { week: (display: string) => `Right: ${display} is your safe amount this week.`, month: (display: string) => `Right: ${display} is your safe amount this month.` },
  close: { week: (display: string) => `Close. ${display} is your safe amount this week.`, month: (display: string) => `Close. ${display} is your safe amount this month.` },
  /** The reveal without a verdict, when there was nothing to choose from. */
  plain: { week: (display: string) => `${display} is your safe amount this week.`, month: (display: string) => `${display} is your safe amount this month.` },
  /** Another option, named by its label. */
  isLabel: (display: string, label: string) => `${display} is ${label}.`,
  concept: 'Safe to spend is the money left for you after your regular bills and your saving are taken care of.',
  none: 'No lesson for this profile today. Ask me anything below.',
}

type LessonStrings = typeof en

const fi: LessonStrings = {
  chip: 'Päivän oppitunti',
  progress: (n, total) => `Oppitunti ${n}/${total}`,
  question: { week: 'Paljonko voit turvallisesti käyttää tällä viikolla?', month: 'Paljonko voit turvallisesti käyttää tässä kuussa?' },
  answers: 'Vastauksesi',
  right: { week: (display) => `Oikein: ${display} on turvallinen summasi tällä viikolla.`, month: (display) => `Oikein: ${display} on turvallinen summasi tässä kuussa.` },
  close: { week: (display) => `Melkein. ${display} on turvallinen summasi tällä viikolla.`, month: (display) => `Melkein. ${display} on turvallinen summasi tässä kuussa.` },
  plain: { week: (display) => `${display} on turvallinen summasi tällä viikolla.`, month: (display) => `${display} on turvallinen summasi tässä kuussa.` },
  isLabel: (display, label) => `${display} on ${label}.`,
  concept: 'Turvallisesti käytettävissä on raha, joka jää sinulle, kun säännölliset laskusi ja säästösi on hoidettu.',
  none: 'Tälle profiilille ei ole tänään oppituntia. Kysy minulta mitä tahansa alla.',
}

export function lessonStrings(lang: Language): LessonStrings {
  return lang === 'fi' ? fi : en
}
