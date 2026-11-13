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
  askTitle: 'Ask Sentti',
  insightsTitle: 'Worth a look',
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
  // Review card texts: owner decision in #68 (the question's {{tokens}} are filled by the app).
  reviewAsks: 'Sentti asks',
  reviewNotSure: 'Not sure',
  reviewQuestion: '{{n1}} at {{category}} on {{date}} — needed, or your choice?',
  reviewAnswers: { unexpected_necessities: 'Needed', everyday_spending: 'My choice' } as Record<string, string>,
  reviewSeePurchase: 'See the purchase',
  reviewSaveFailed: 'Your answer was not saved. Try again.',
  undo: 'Undo',
  was: (display: string) => `was ${display}`,
  staysSame: 'stays the same',
  chatSoon: 'Sentti will answer here in the next build. For now, every number on the overview opens its transactions.',
  toOverview: 'Back to overview',
  mockBadge: 'Mock data',
  heroPendingTitle: 'Safe to spend this week',
  heroPending: 'Safe to spend is still being calculated. Check back soon.',
  showMore: 'Show more',
  crash: 'Something went wrong on this screen.',
  reload: 'Reload',
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
  askTitle: 'Kysy Senttiltä',
  insightsTitle: 'Huomioita',
  status: {
    ok: 'Hyvällä mallilla tällä viikolla',
    below_usual: 'Tavallista vähemmän liikkumavaraa',
    nothing_free: 'Tällä viikolla ei vapaata rahaa',
  },
  keptAside: 'varattuna',
  chipHint: 'Näytä, miten luku laskettiin',
  howCalculated: 'Näin luku laskettiin',
  madeOf: 'Mistä luku koostuu',
  transactions: 'Tapahtumat',
  reconciles: 'Nämä tapahtumat täsmäävät yllä olevaan lukuun.',
  method: 'Menetelmä',
  reviewAsks: 'Sentti kysyy',
  reviewNotSure: 'En ole varma',
  reviewQuestion: '{{n1}} {{category}}, {{date}} — välttämätön hankinta vai oma valinta?',
  reviewAnswers: { unexpected_necessities: 'Välttämätön', everyday_spending: 'Oma valinta' },
  reviewSeePurchase: 'Näytä ostos',
  reviewSaveFailed: 'Vastausta ei tallennettu. Yritä uudelleen.',
  undo: 'Peru',
  was: (display: string) => `aiemmin ${display}`,
  staysSame: 'pysyy ennallaan',
  chatSoon: 'Sentti vastaa tässä seuraavassa versiossa. Nyt jokainen yleiskuvan luku avaa omat tapahtumansa.',
  toOverview: 'Takaisin yleiskuvaan',
  mockBadge: 'Testidata',
  heroPendingTitle: 'Käyttövara tällä viikolla',
  heroPending: 'Käyttövaraa lasketaan vielä. Katso hetken päästä uudelleen.',
  showMore: 'Näytä lisää',
  crash: 'Tällä näkymällä tapahtui virhe.',
  reload: 'Lataa uudelleen',
}

export function strings(lang: Language): Strings {
  return lang === 'fi' ? fi : en
}

export function parseLanguage(value: string | null): Language {
  return value === 'fi' ? 'fi' : 'en'
}

/** Raw evidence rows carry a signed decimal string; this only formats it for reading. */
export function formatRowAmount(amount: string, currency: string, lang: Language): string {
  const value = Number(amount)
  if (!Number.isFinite(value)) return `${amount} ${currency}`
  return new Intl.NumberFormat(lang === 'fi' ? 'fi-FI' : 'en-IE', { style: 'currency', currency }).format(value)
}

export function formatDate(date: string, lang: Language): string {
  const parsed = new Date(`${date}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return date
  return new Intl.DateTimeFormat(lang === 'fi' ? 'fi-FI' : 'en-GB', { day: 'numeric', month: 'short' }).format(parsed)
}
