// The chat screen's own strings (DESIGN.md section 6: short, friendly, no moralising).
// Texts from the API (answers, labels, `display`, error messages) are shown as received.
import type { Language } from '../api/types.ts'

const en = {
  sentti: 'Sentti',
  can: 'I can explain where your money went, what you can safely spend this week and where you could save, using your own transactions. I can’t give investment advice or decide on loans.',
  starters: ['Where did my money go?', 'What can I safely spend this week?', 'How could I save more?'],
  placeholder: 'Ask about your money',
  inputLabel: 'Your question',
  send: 'Send',
  stop: 'Stop the answer',
  stages: {
    understanding: 'Reading your question',
    tool: 'Checking your transactions',
    writing: 'Writing',
  },
  stageDone: 'done',
  stageNow: 'in progress',
  stagesLabel: 'Progress',
  orType: 'Or type your answer',
  /** The bill reading's fact marker only; chat answers carry no source label (#685). */
  fact: 'From your transactions',
  templateNote: 'Written from a standard template this time, without the AI model. The numbers are the same.',
  stopped: 'You stopped this answer.',
  askAgain: 'Ask again',
  /** A paste over the 500-character limit was cut to fit (#716). */
  cut: 'Cut to the 500-character limit.',
  /** Shown when 50 characters or fewer are left. */
  charactersLeft: (left: number) => (left === 1 ? '1 character left' : `${left} characters left`),
  more: 'more',
  less: 'less',
  same: 'no change',
  flags: { one_off: 'One-off', habit: 'Habit' } as Record<string, string>,
  errors: {
    network: 'No connection. Check your network and try again.',
    bad_response: 'Something went wrong. Try again.',
    bad_stream: 'The answer came back garbled. Try again.',
    stream_ended: 'The answer was cut off. Try again.',
  } as Record<string, string>,
}

type ChatStrings = typeof en

const fi: ChatStrings = {
  sentti: 'Sentti',
  can: 'Voin kertoa tilitapahtumiesi perusteella, mihin rahasi menivät, paljonko voit turvallisesti käyttää tällä viikolla ja mistä voisit säästää. En anna sijoitusneuvoja enkä tee lainapäätöksiä.',
  starters: ['Mihin rahani menivät?', 'Paljonko voin turvallisesti käyttää tällä viikolla?', 'Miten voisin säästää enemmän?'],
  placeholder: 'Kysy raha-asioistasi',
  inputLabel: 'Kysymyksesi',
  send: 'Lähetä',
  stop: 'Pysäytä vastaus',
  stages: {
    understanding: 'Luen kysymystäsi',
    tool: 'Tarkistan tilitapahtumasi',
    writing: 'Kirjoitan',
  },
  stageDone: 'valmis',
  stageNow: 'käynnissä',
  stagesLabel: 'Eteneminen',
  orType: 'Tai kirjoita vastauksesi',
  fact: 'Tilitapahtumistasi',
  templateNote: 'Kirjoitettu tällä kertaa vakiopohjalla ilman tekoälymallia. Luvut ovat samat.',
  stopped: 'Pysäytit tämän vastauksen.',
  askAgain: 'Kysy uudelleen',
  cut: 'Lyhennetty 500 merkkiin.',
  charactersLeft: (left: number) => (left === 1 ? '1 merkki jäljellä' : `${left} merkkiä jäljellä`),
  more: 'enemmän',
  less: 'vähemmän',
  same: 'ei muutosta',
  flags: { one_off: 'Kertaostos', habit: 'Tapa' },
  errors: {
    network: 'Ei yhteyttä. Tarkista verkkoyhteys ja yritä uudelleen.',
    bad_response: 'Jokin meni vikaan. Yritä uudelleen.',
    bad_stream: 'Vastaus tuli perille sekaisin. Yritä uudelleen.',
    stream_ended: 'Vastaus katkesi. Yritä uudelleen.',
  },
}

export function chatStrings(lang: Language): ChatStrings {
  return lang === 'fi' ? fi : en
}

/** Errors the app makes itself (no connection, a broken stream) get the app's own text; the API's arrive localised. */
export function errorMessage(error: { code: string; message: string }, s: ChatStrings): string {
  return s.errors[error.code] ?? error.message
}
