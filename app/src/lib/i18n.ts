// The app's own strings. Everything that comes from the API (labels, `display`, texts)
// arrives already localised and is shown as is (contract section 1).
import type { Language } from '../api/types.ts'

const en = {
  disclosure: 'Sentti is an AI assistant. Numbers come from your transactions.',
  back: 'Back',
  close: 'Close',
  loading: 'Loading…',
  retry: 'Try again',
  switchPersona: 'Switch demo persona',
  personaTitle: 'Demo persona',
  personaHint: 'Demo personas are synthetic customers. Long press the header to come back here.',
  language: 'Language',
  insightsTitle: 'Worth a look',
  billsNext: (date: string) => `Next ${date}`,
  billsRounding: 'Each bill is rounded on its own, so together they can differ from the total by up to €0.01 per bill.',
  status: {
    ok: 'On track this week',
    below_usual: 'Less room than usual',
    nothing_free: 'Nothing free this week',
  },
  keptAside: 'kept aside',
  chipHint: 'Show how it was calculated',
  howCalculated: 'How it was calculated',
  madeOf: 'What it is made of',
  transactions: 'Transactions',
  reconciles: 'These transactions add up to the number above.',
  method: 'Method',
  // Review card frame; the question and the answers come from the API (`question`, `options[].label`).
  reviewAsks: 'Sentti asks',
  /** Before the API's question in the opening's bubble (Renat's light redesign). */
  reviewQuick: 'Quick question:',
  reviewNotSure: 'Not sure',
  /** After "Not sure" (Renat's review): the toast, the line left behind and its way back. */
  reviewHidden: 'Question hidden for now.',
  reviewSkipped: 'You skipped Sentti’s question.',
  reviewChange: 'Change answer',
  reviewSeePurchase: 'See the purchase',
  reviewSaveFailed: 'Your answer was not saved. Try again.',
  undo: 'Undo',
  retryIn: (seconds: number) => `Try again in ${seconds} s`,
  was: (display: string) => `was ${display}`,
  staysSame: 'stays the same',
  // The opening turn (#310 decision: one thought per screen). Captions stay under 8 words.
  // By `hero.status`, no numbers in the words (#408 review).
  heroCaption: {
    ok: 'left to spend this week',
    below_usual: 'less room than usual this week',
    nothing_free: 'nothing free to spend this week',
  } as Record<string, string>,
  /** Under the hero's caption: what the weekly figure has already taken out (metrics.md section 3). */
  heroAfter: 'After bills, essentials, a surprise reserve and savings',
  movedTo: 'Moved to',
  heroHowMade: 'Show how it is made',
  aboutSentti: 'How Sentti works',
  /** The accessible name of the header title ("Sentti" with its AI tag). */
  titleLabel: 'Sentti — how Sentti works',
  reviewWhy: 'Why Sentti asks',
  questionsLabel: 'Questions to ask',
  /** The overview sheet's title and the header button's name (#321, #322). */
  overview: 'Overview',
  /** The header's profile icon opens this menu (Renat's light redesign): overview, How Sentti works, personas. */
  menu: 'Menu',
  /** A short hint, once per visit, for the header icons and the paperclip (Renat's review). */
  firstHint: 'Tip: the pencil starts a new chat, the profile icon opens the overview, and the paperclip shows Sentti a bill.',
  gotIt: 'Got it',
  /** Under a comparison with people like you (Renat's review). */
  peerContext: 'Context, not a target.',
  /** The overview sheet's collapsible sections under the main answer (Renat's review). */
  overviewSections: { money: 'Where the money goes', bills: 'Bills until payday', save: 'What you can set aside' } as Record<string, string>,
  /** The header's pencil button: empties the thread (asks first when there is something in it). */
  newChat: 'New chat',
  /** The folded opening's line after the first message: the amount is the API's `display`. */
  foldLeft: (display: string) => `Left to spend ${display}`,
  foldQuestions: (n: number) => (n === 1 ? '1 question from Sentti' : `${n} questions from Sentti`),
  newChatConfirm: 'This clears the conversation and the lesson progress.',
  cancel: 'Cancel',
  mockBadge: 'Mock data',
  heroPendingTitle: 'Left to spend this week',
  heroPending: 'Left to spend is still being calculated. Check back soon.',
  showMore: 'Show more',
  crash: 'Something went wrong on this screen.',
  reload: 'Reload',
  errorGeneric: 'Something went wrong.',
  errorRetry: 'Something went wrong. Try again.',
  errorOffline: 'No connection. Try again.',
  saveSeparate: 'Safe to save is separate from safe to spend and is never added to it.',
  whatIfTitle: 'What if',
  whatIfEntry: 'What if I spent 20% less on restaurants?',
  whatIfCut: 'Spend less by',
  whatIfCutValue: (pct: number) => `${pct}% less`,
  whatIfUpdating: 'Updating…',
  whatIfBaseline: 'Now',
  whatIfAssumptions: 'Assumptions',
}

type Strings = typeof en

const fi: Strings = {
  disclosure: 'Sentti on tekoälyavustaja. Luvut tulevat tilitapahtumistasi.',
  back: 'Takaisin',
  close: 'Sulje',
  loading: 'Ladataan…',
  retry: 'Yritä uudelleen',
  switchPersona: 'Vaihda demohenkilö',
  personaTitle: 'Demohenkilö',
  personaHint: 'Demohenkilöt ovat synteettisiä asiakkaita. Pitkä painallus otsikkoon tuo sinut takaisin tänne.',
  language: 'Kieli',
  insightsTitle: 'Huomioita',
  billsNext: (date: string) => `Seuraava ${date}`,
  billsRounding: 'Jokainen lasku pyöristetään erikseen, joten yhteensä ne voivat poiketa kokonaissummasta enintään 0,01 € laskua kohden.',
  status: {
    ok: 'Hyvällä mallilla tällä viikolla',
    below_usual: 'Tavallista vähemmän liikkumavaraa',
    nothing_free: 'Tällä viikolla ei vapaata rahaa',
  },
  keptAside: 'varattuna',
  chipHint: 'Näytä, miten luku lasketaan',
  howCalculated: 'Näin luku lasketaan',
  madeOf: 'Mistä luku koostuu',
  transactions: 'Tapahtumat',
  reconciles: 'Nämä tapahtumat täsmäävät yllä olevaan lukuun.',
  method: 'Menetelmä',
  reviewAsks: 'Sentti kysyy',
  reviewQuick: 'Pikakysymys:',
  reviewNotSure: 'En ole varma',
  reviewHidden: 'Kysymys piilotettu toistaiseksi.',
  reviewSkipped: 'Ohitit Sentin kysymyksen.',
  reviewChange: 'Muuta vastausta',
  reviewSeePurchase: 'Näytä ostos',
  reviewSaveFailed: 'Vastausta ei tallennettu. Yritä uudelleen.',
  undo: 'Peru',
  retryIn: (seconds: number) => `Yritä uudelleen ${seconds} s kuluttua`,
  was: (display: string) => `aiemmin ${display}`,
  staysSame: 'pysyy ennallaan',
  heroCaption: {
    ok: 'käyttövara tällä viikolla',
    below_usual: 'tällä viikolla tavallista vähemmän',
    nothing_free: 'tällä viikolla ei vapaata käytettävää',
  },
  heroAfter: 'Laskujen, perusmenojen, yllätysvarauksen ja säästön jälkeen',
  movedTo: 'Siirretty:',
  heroHowMade: 'Näytä, miten se lasketaan',
  aboutSentti: 'Näin Sentti toimii',
  titleLabel: 'Sentti — näin Sentti toimii',
  reviewWhy: 'Miksi Sentti kysyy',
  questionsLabel: 'Kysymyksiä',
  overview: 'Yleiskatsaus',
  menu: 'Valikko',
  firstHint: 'Vinkki: kynä aloittaa uuden keskustelun, profiilikuvake avaa yleiskatsauksen ja paperiliitin näyttää Sentille laskun.',
  gotIt: 'Selvä',
  peerContext: 'Taustatietoa, ei tavoite.',
  overviewSections: { money: 'Mihin raha menee', bills: 'Laskut palkkapäivään', save: 'Mitä voit säästää' },
  newChat: 'Uusi keskustelu',
  foldLeft: (display: string) => `Käyttövara ${display}`,
  foldQuestions: (n: number) => (n === 1 ? '1 kysymys Senttiltä' : `${n} kysymystä Senttiltä`),
  newChatConfirm: 'Tämä tyhjentää keskustelun ja oppituntien edistymisen.',
  cancel: 'Peruuta',
  mockBadge: 'Testidata',
  heroPendingTitle: 'Käyttövara tällä viikolla',
  heroPending: 'Käyttövaraa lasketaan vielä. Katso hetken päästä uudelleen.',
  showMore: 'Näytä lisää',
  crash: 'Tällä näkymällä tapahtui virhe.',
  reload: 'Lataa uudelleen',
  errorGeneric: 'Jokin meni vikaan.',
  errorRetry: 'Jokin meni vikaan. Yritä uudelleen.',
  errorOffline: 'Ei yhteyttä. Yritä uudelleen.',
  saveSeparate: 'Säästövara on eri asia kuin käyttövara, eikä niitä lasketa yhteen.',
  whatIfTitle: 'Entä jos',
  whatIfEntry: 'Entä jos käyttäisin 20 % vähemmän ravintoloihin?',
  whatIfCut: 'Käytä vähemmän',
  whatIfCutValue: (pct: number) => `${pct} % vähemmän`,
  whatIfUpdating: 'Päivitetään…',
  whatIfBaseline: 'Nyt',
  whatIfAssumptions: 'Oletukset',
}

export function strings(lang: Language): Strings {
  return lang === 'fi' ? fi : en
}

export function parseLanguage(value: string | null): Language {
  return value === 'fi' ? 'fi' : 'en'
}

export function formatDate(date: string, lang: Language): string {
  const parsed = new Date(`${date}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return date
  return new Intl.DateTimeFormat(lang === 'fi' ? 'fi-FI' : 'en-GB', { day: 'numeric', month: 'short' }).format(parsed)
}
