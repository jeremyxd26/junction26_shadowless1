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
  reviewSoon: 'Answering here comes in the next build.',
  chatSoon: 'Sentti will answer here in the next build. For now, every number on the overview opens its transactions.',
  toOverview: 'Back to overview',
  mockBadge: 'Mock data',
  heroPendingTitle: 'Safe to spend this week',
  heroPending: 'Safe to spend is still being calculated. Check back soon.',
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
  askTitle: 'Kysy Senttiltä',
  insightsTitle: 'Huomioita',
  billsNext: (date: string) => `Seuraava ${date}`,
  billsRounding: 'Jokainen lasku pyöristetään erikseen, joten yhteensä ne voivat poiketa kokonaissummasta enintään 0,01 € laskua kohden.',
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
  reviewSoon: 'Vastaaminen tulee seuraavassa versiossa.',
  chatSoon: 'Sentti vastaa tässä seuraavassa versiossa. Nyt jokainen yleiskuvan luku avaa omat tapahtumansa.',
  toOverview: 'Takaisin yleiskuvaan',
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
