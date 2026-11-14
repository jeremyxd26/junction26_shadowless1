import type { Language } from '../../api/types.ts'

// The Learn tab's own words, EN and FI, short; no numbers (they come from the API's `display`).

const en = {
  tabs: 'Sentti',
  tabChat: 'Chat',
  tabLearn: 'Learn',
  title: 'Learn',
  intro: 'Short lessons on your own numbers. Each takes about a minute.',
  overall: (done: number, total: number) => `${done} of ${total} lessons`,
  topicProgress: (done: number, total: number) => `${done}/${total}`,
  continue: 'Continue',
  again: 'Go through again',
  allDone: 'All lessons done. You can go through them again any time.',
  noLessons: 'Lessons appear once your numbers have loaded.',
  doneMark: 'done',
  back: 'Back to topics',
  reset: 'Reset progress',
  storageNote: 'Your progress is kept only in this browser: which lessons you finished, nothing else.',
  topics: {
    money: 'Where the money goes',
  } as Record<string, string>,
  lessons: {
    'money-1': 'Left to spend this week',
    'money-2': 'Where your money goes',
    'money-3': 'How much you can set aside',
  } as Record<string, string>,
}

type LearnStrings = typeof en

const fi: LearnStrings = {
  tabs: 'Sentti',
  tabChat: 'Keskustelu',
  tabLearn: 'Opi',
  title: 'Opi',
  intro: 'Lyhyitä oppitunteja omista luvuistasi. Kukin vie noin minuutin.',
  overall: (done, total) => `${done}/${total} oppituntia`,
  topicProgress: (done, total) => `${done}/${total}`,
  continue: 'Jatka',
  again: 'Käy uudelleen',
  allDone: 'Kaikki oppitunnit tehty. Voit käydä ne uudelleen milloin vain.',
  noLessons: 'Oppitunnit näkyvät, kun lukusi on ladattu.',
  doneMark: 'tehty',
  back: 'Takaisin aiheisiin',
  reset: 'Nollaa edistyminen',
  storageNote: 'Edistymisesi tallentuu vain tähän selaimeen: mitkä oppitunnit teit, ei muuta.',
  topics: {
    money: 'Mihin raha menee',
  },
  lessons: {
    'money-1': 'Käyttövara tällä viikolla',
    'money-2': 'Mihin rahasi menevät',
    'money-3': 'Paljonko voit säästää',
  },
}

export function learnStrings(lang: Language): LearnStrings {
  return lang === 'fi' ? fi : en
}
