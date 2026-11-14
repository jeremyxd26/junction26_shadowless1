import type { Language, OverviewResponse } from '../../api/types.ts'
import { lessonTwo } from '../lesson/lessons.ts'

// The Learn tab's glossary (#764): about twelve terms tied to the product, one or two plain sentences
// each. Where the overview has the figure, "In your numbers" shows the API's own `display`; without it
// the line is left out. No contract field is added and nothing is formatted here.

type Figure = (overview: OverviewResponse | null) => string | null

interface Term {
  id: string
  term: { en: string; fi: string }
  text: { en: string; fi: string }
  figure?: Figure
}

const basket =
  (key: string): Figure =>
  (overview) =>
    lessonTwo(overview)?.rows.find((row) => row.key === key)?.display ?? null

const TERMS: Term[] = [
  {
    id: 'left',
    term: { en: 'Left to spend (käyttövara)', fi: 'Käyttövara' },
    text: {
      en: 'What you can spend this week once bills, usual essentials, a reserve for surprises and your savings are taken out.',
      fi: 'Summa, jonka voit käyttää tällä viikolla, kun laskut, tavalliset perusmenot, yllätysvaraus ja säästö on vähennetty.',
    },
    figure: (overview) => overview?.hero?.primary.display ?? null,
  },
  {
    id: 'fixed',
    term: { en: 'Fixed costs', fi: 'Kiinteät menot' },
    text: {
      en: 'Costs that come every month at about the same size: rent, electricity, insurance, a phone plan.',
      fi: 'Menot, jotka tulevat joka kuukausi suunnilleen samansuuruisina: vuokra, sähkö, vakuutukset, puhelinliittymä.',
    },
    figure: basket('regular_essentials'),
  },
  {
    id: 'everyday',
    term: { en: 'Everyday spending', fi: 'Arjen kulutus' },
    text: {
      en: 'What you choose day to day, such as eating out, hobbies and shopping. It is the easiest part to adjust.',
      fi: 'Päivittäin itse valitsemasi kulutus, kuten ulkona syöminen, harrastukset ja ostokset. Sitä on helpointa säätää.',
    },
    figure: basket('everyday_spending'),
  },
  {
    id: 'irregular',
    term: { en: 'Irregular must-haves', fi: 'Epäsäännölliset välttämättömät menot' },
    text: {
      en: 'Costs you must pay but cannot plan to the day, such as a repair or a dentist visit. Sentti keeps a reserve for them.',
      fi: 'Menot, jotka on pakko maksaa mutta joita ei voi suunnitella päivälleen, kuten korjaus tai hammaslääkäri. Sentti pitää niitä varten varausta.',
    },
    figure: basket('unexpected_necessities'),
  },
  {
    id: 'buffer',
    term: { en: 'Buffer', fi: 'Puskuri' },
    text: {
      en: 'Money kept aside for surprises, so one unexpected bill does not knock your month off track. Many aim for at least a month of essential costs.',
      fi: 'Sivuun pantu raha yllätyksiä varten, jotta yksi odottamaton lasku ei kaada kuukautta. Moni tavoittelee vähintään kuukauden välttämättömiä menoja.',
    },
  },
  {
    id: 'rate',
    term: { en: 'Savings rate', fi: 'Säästöaste' },
    text: {
      en: 'The share of your income you put aside, for example 10 % of each salary. Saving first, before spending, makes it happen.',
      fi: 'Osuus tuloistasi, jonka panet sivuun, esimerkiksi 10 % jokaisesta palkasta. Kun säästät ensin, ennen kuluttamista, se toteutuu.',
    },
  },
  {
    id: 'median',
    term: { en: 'Median (people like you)', fi: 'Mediaani (kaltaisesi ihmiset)' },
    text: {
      en: 'The middle value: half of a group is above it, half below. Sentti compares you with the median of people in a similar situation, so a few very big spenders do not skew it.',
      fi: 'Keskimmäinen arvo: puolet ryhmästä on sen yläpuolella ja puolet alapuolella. Sentti vertaa sinua samankaltaisten ihmisten mediaaniin, joten muutama poikkeuksellisen suuri kuluttaja ei vääristä vertailua.',
    },
  },
  {
    id: 'reference',
    term: { en: 'Reference number (viitenumero)', fi: 'Viitenumero' },
    text: {
      en: 'The number on a bill that tells the payee which bill you paid. Copy it exactly; it can also start with RF.',
      fi: 'Laskun numero, josta laskuttaja tunnistaa, minkä laskun maksoit. Kopioi se tarkasti; se voi alkaa myös kirjaimilla RF.',
    },
  },
  {
    id: 'due',
    term: { en: 'Due date (eräpäivä)', fi: 'Eräpäivä' },
    text: {
      en: 'The last day to pay a bill. Paying late can bring a reminder fee and late-payment interest.',
      fi: 'Viimeinen päivä maksaa lasku. Myöhästyminen voi tuoda muistutusmaksun ja viivästyskorkoa.',
    },
  },
  {
    id: 'iban',
    term: { en: 'IBAN', fi: 'IBAN' },
    text: {
      en: "The payee's account number. A Finnish IBAN starts with FI and has 18 characters.",
      fi: 'Laskuttajan tilinumero. Suomalainen IBAN alkaa kirjaimilla FI ja siinä on 18 merkkiä.',
    },
  },
  {
    id: 'einvoice',
    term: { en: 'E-invoice (e-lasku)', fi: 'E-lasku' },
    text: {
      en: 'A bill that comes straight to your online bank. You check and approve it there, or let the bank pay it automatically.',
      fi: 'Lasku, joka tulee suoraan verkkopankkiisi. Tarkistat ja hyväksyt sen siellä, tai annat pankin maksaa sen automaattisesti.',
    },
  },
  {
    id: 'direct',
    term: { en: 'Direct payment (suoramaksu)', fi: 'Suoramaksu' },
    text: {
      en: 'The bank pays an agreed bill from your account on its due date. The payee tells you the amount beforehand.',
      fi: 'Pankki maksaa sovitun laskun tililtäsi eräpäivänä. Laskuttaja ilmoittaa summan sinulle etukäteen.',
    },
  },
]

export interface GlossaryEntry {
  id: string
  term: string
  text: string
  /** The API's display for "In your numbers", or null to leave the line out. */
  figure: string | null
}

export function glossary(overview: OverviewResponse | null, lang: Language): GlossaryEntry[] {
  return TERMS.map((entry) => ({
    id: entry.id,
    term: entry.term[lang === 'fi' ? 'fi' : 'en'],
    text: entry.text[lang === 'fi' ? 'fi' : 'en'],
    figure: entry.figure?.(overview) ?? null,
  }))
}
