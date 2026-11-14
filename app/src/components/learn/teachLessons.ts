import type { Language, OverviewResponse } from '../../api/types.ts'
import { lessonTwo } from '../lesson/lessons.ts'

// The Learn tab's lessons (#764), each taught in four steps: a short teach card, the customer's own
// numbers (the API's `display`, never formatted here), one check question that is about the idea (its
// options are words, not mixed amounts), and a takeaway. Our own short texts, EN and FI; no products,
// funds, shares or loans. The bills lessons show a sample bill's fields (synthetic data), marked as such.

export type LessonIcon = 'pie' | 'baskets' | 'save' | 'reference' | 'account' | 'auto' | 'payday' | 'buffer'

export interface TeachLesson {
  key: string
  icon: LessonIcon
  title: string
  /** Two or three plain sentences. */
  teach: string
  /** The numbers card's title ("Your numbers", or "On a sample bill"). */
  numbersTitle: string
  /** The figures: our own label and the API's display (or a sample field); empty: no numbers card. */
  numbers: { label: string; display: string }[]
  check: { question: string; options: { key: string; text: string }[]; right: string; explain: string }
  takeaway: string
}

const SAMPLE = { iban: 'FI09 1234 5600 0010 01', reference: '104521100', due: '8.10.2026' }

type Pair = { en: string; fi: string }
const pick = (lang: Language, pair: Pair) => (lang === 'fi' ? pair.fi : pair.en)

function figures(lang: Language, list: [Pair, string | null | undefined][]) {
  return list.filter((entry): entry is [Pair, string] => Boolean(entry[1])).map(([label, display]) => ({ label: pick(lang, label), display }))
}

export function teachLessons(topic: string, overview: OverviewResponse | null, lang: Language): TeachLesson[] {
  const t = (en: string, fi: string) => (lang === 'fi' ? fi : en)
  const yours = t('Your numbers', 'Sinun lukusi')
  const sample = t('On a sample bill', 'Esimerkkilaskulla')
  const rows = lessonTwo(overview)?.rows ?? []
  const row = (key: string) => rows.find((item) => item.key === key)?.display
  const save = overview?.safe_to_save

  if (topic === 'bills') {
    return [
      {
        key: 'bills-1',
        icon: 'reference',
        title: t('The reference number (viitenumero)', 'Viitenumero'),
        teach: t(
          'Every Finnish bill has a reference number. When you pay, it tells the payee which bill the money is for. It can also start with RF.',
          'Jokaisessa suomalaisessa laskussa on viitenumero. Kun maksat, se kertoo laskuttajalle, mihin laskuun raha kuuluu. Se voi alkaa myös kirjaimilla RF.',
        ),
        numbersTitle: sample,
        numbers: figures(lang, [[{ en: 'Reference number', fi: 'Viitenumero' }, SAMPLE.reference]]),
        check: {
          question: t('What does the reference number do?', 'Mitä viitenumero tekee?'),
          options: [
            { key: 'match', text: t('Matches your payment to the right bill', 'Kohdistaa maksusi oikeaan laskuun') },
            { key: 'id', text: t('Proves who you are', 'Todistaa henkilöllisyytesi') },
            { key: 'date', text: t('Sets the due date', 'Asettaa eräpäivän') },
          ],
          right: 'match',
          explain: t(
            'The reference number only matches the payment to the bill; with a wrong one the payee may not see it as paid.',
            'Viitenumero vain kohdistaa maksun laskuun; väärällä viitteellä laskuttaja ei ehkä näe laskua maksetuksi.',
          ),
        },
        takeaway: t('Copy the reference number exactly, or let your bank read the bill for you.', 'Kopioi viitenumero tarkasti tai anna pankin lukea lasku puolestasi.'),
      },
      {
        key: 'bills-2',
        icon: 'account',
        title: t('IBAN and the due date (eräpäivä)', 'IBAN ja eräpäivä'),
        teach: t(
          "The IBAN is the payee's account number: a Finnish one starts with FI and has 18 characters. The due date is the last day to pay without a reminder fee or late-payment interest.",
          'IBAN on laskuttajan tilinumero: suomalainen alkaa kirjaimilla FI ja siinä on 18 merkkiä. Eräpäivä on viimeinen päivä maksaa ilman muistutusmaksua tai viivästyskorkoa.',
        ),
        numbersTitle: sample,
        numbers: figures(lang, [
          [{ en: 'IBAN', fi: 'IBAN' }, SAMPLE.iban],
          [{ en: 'Due date', fi: 'Eräpäivä' }, SAMPLE.due],
        ]),
        check: {
          question: t('Which field tells where your money goes?', 'Mistä kentästä näet, minne rahasi menevät?'),
          options: [
            { key: 'iban', text: t('The IBAN', 'IBAN') },
            { key: 'due', text: t('The due date', 'Eräpäivä') },
            { key: 'ref', text: t('The reference number', 'Viitenumero') },
          ],
          right: 'iban',
          explain: t('The IBAN is the account the money goes to; the due date only says when.', 'IBAN on tili, jolle raha menee; eräpäivä kertoo vain milloin.'),
        },
        takeaway: t('Check the IBAN before you pay, and pay by the due date.', 'Tarkista IBAN ennen maksamista ja maksa eräpäivään mennessä.'),
      },
      {
        key: 'bills-3',
        icon: 'auto',
        title: t('E-invoice and direct payment', 'E-lasku ja suoramaksu'),
        teach: t(
          'An e-invoice (e-lasku) comes straight to your online bank, where you approve it or let the bank pay it. With direct payment (suoramaksu) the bank pays an agreed bill on its due date, and the payee tells you the amount beforehand.',
          'E-lasku tulee suoraan verkkopankkiisi, jossa hyväksyt sen tai annat pankin maksaa sen. Suoramaksussa pankki maksaa sovitun laskun eräpäivänä, ja laskuttaja ilmoittaa summan etukäteen.',
        ),
        numbersTitle: '',
        numbers: [],
        check: {
          question: t(
            'You want a bill paid on its due date without approving it each month. Which fits?',
            'Haluat laskun maksetuksi eräpäivänä hyväksymättä sitä joka kuukausi. Mikä sopii?',
          ),
          options: [
            { key: 'direct', text: t('Direct payment (suoramaksu)', 'Suoramaksu') },
            { key: 'paper', text: t('A paper bill', 'Paperilasku') },
            { key: 'cash', text: t('Paying at a counter', 'Maksu tiskillä') },
          ],
          right: 'direct',
          explain: t('Direct payment pays the agreed bill on its due date; paper and counter bills need you each time.', 'Suoramaksu maksaa sovitun laskun eräpäivänä; paperi- ja tiskimaksu tarvitsevat sinua joka kerta.'),
        },
        takeaway: t('Automatic payment helps, as long as the money is on the account on the due date.', 'Automaattinen maksu auttaa, kunhan raha on tilillä eräpäivänä.'),
      },
    ]
  }

  if (topic === 'saving') {
    return [
      {
        key: 'saving-1',
        icon: 'payday',
        title: t('Pay yourself first', 'Maksa ensin itsellesi'),
        teach: t(
          'Saving works best when it happens first, right after payday, before the spending starts. An automatic transfer makes it a habit you do not have to remember.',
          'Säästäminen onnistuu parhaiten, kun se tapahtuu ensin, heti palkkapäivänä, ennen kuin kuluttaminen alkaa. Automaattinen siirto tekee siitä tavan, jota ei tarvitse muistaa.',
        ),
        numbersTitle: yours,
        numbers: figures(lang, [
          [{ en: 'You can typically put aside', fi: 'Voit tavallisesti säästää' }, save?.monthly.display],
          [{ en: 'That is, each week', fi: 'Eli viikossa' }, save?.weekly?.display],
        ]),
        check: {
          question: t('When is saving easiest?', 'Milloin säästäminen onnistuu helpoimmin?'),
          options: [
            { key: 'payday', text: t('Right after payday, automatically', 'Heti palkkapäivänä, automaattisesti') },
            { key: 'end', text: t('At the end of the month, if anything is left', 'Kuun lopussa, jos jotain jää') },
            { key: 'big', text: t('Only before a big purchase', 'Vain ennen isoa hankintaa') },
          ],
          right: 'payday',
          explain: t('What is left at the end of the month is often nothing; saving first makes it happen.', 'Kuun lopussa jää usein ei mitään; säästämällä ensin säästö toteutuu.'),
        },
        takeaway: t('Set the saving to move on payday, then spend from what is left.', 'Ajasta säästö siirtymään palkkapäivänä ja kuluta siitä, mitä jää.'),
      },
      {
        key: 'saving-2',
        icon: 'buffer',
        title: t('A buffer for surprises', 'Puskuri yllätyksiä varten'),
        teach: t(
          'A buffer is money kept aside for costs you must pay but cannot plan to the day, like a repair or a dentist bill. Sentti already keeps a reserve for them in your left to spend.',
          'Puskuri on sivuun pantua rahaa menoihin, jotka on pakko maksaa mutta joita ei voi suunnitella päivälleen, kuten korjaus tai hammaslääkäri. Sentti pitää niitä varten varausta jo käyttövarassasi.',
        ),
        numbersTitle: yours,
        numbers: figures(lang, [[{ en: 'Your irregular must-haves', fi: 'Epäsäännölliset välttämättömät menosi' }, row('unexpected_necessities')]]),
        check: {
          question: t('A surprise dentist bill arrives. What keeps your month on track?', 'Yllättävä hammaslääkärilasku tulee. Mikä pitää kuukauden raiteillaan?'),
          options: [
            { key: 'buffer', text: t('A buffer kept aside', 'Sivuun pantu puskuri') },
            { key: 'late', text: t('Paying the bill late', 'Laskun maksaminen myöhässä') },
            { key: 'food', text: t('Cutting back on groceries', 'Ruokaostoksista tinkiminen') },
          ],
          right: 'buffer',
          explain: t('Paying late adds fees, and cutting food hurts; a buffer is there for exactly this.', 'Myöhästyminen tuo kuluja ja ruoasta tinkiminen on raskasta; puskuri on juuri tätä varten.'),
        },
        takeaway: t('Many start with about a month of essential costs as a buffer and build from there.', 'Moni aloittaa noin kuukauden välttämättömistä menoista ja kasvattaa puskuria siitä.'),
      },
    ]
  }

  // "Where the money goes"
  return [
    {
      key: 'money-1',
      icon: 'pie',
      title: t('Left to spend this week', 'Käyttövara tällä viikolla'),
      teach: t(
        'Left to spend is what you can use this week without touching what is already spoken for. Sentti takes out your bills, usual essentials, a reserve for surprises and your savings first.',
        'Käyttövara on se, minkä voit käyttää tällä viikolla koskematta jo varattuun rahaan. Sentti vähentää ensin laskut, tavalliset perusmenot, yllätysvarauksen ja säästön.',
      ),
      numbersTitle: yours,
      numbers: figures(lang, [[{ en: 'Left to spend this week', fi: 'Käyttövara tällä viikolla' }, overview?.hero?.primary.display]]),
      check: {
        question: t('What is taken out before left to spend?', 'Mitä vähennetään ennen käyttövaraa?'),
        options: [
          { key: 'all', text: t('Bills, usual essentials, a surprise reserve and savings', 'Laskut, perusmenot, yllätysvaraus ja säästö') },
          { key: 'rent', text: t('Only the rent', 'Vain vuokra') },
          { key: 'none', text: t('Nothing, it is your balance', 'Ei mitään, se on saldosi') },
        ],
        right: 'all',
        explain: t('Left to spend is not your balance: bills, essentials, a reserve and savings come out first.', 'Käyttövara ei ole saldosi: laskut, perusmenot, varaus ja säästö vähennetään ensin.'),
      },
      takeaway: t('Spend from left to spend, and the rest of your plan stays safe.', 'Kuluta käyttövarasta, niin muu suunnitelmasi pysyy turvassa.'),
    },
    {
      key: 'money-2',
      icon: 'baskets',
      title: t('Where your money goes', 'Mihin rahasi menevät'),
      teach: t(
        'Sentti sorts spending into three baskets: regular essentials you pay every month, irregular must-haves you cannot plan to the day, and everyday spending you choose.',
        'Sentti jakaa kulutuksen kolmeen koriin: säännölliset välttämättömät menot joka kuukausi, epäsäännölliset pakolliset menot, joita ei voi suunnitella päivälleen, ja itse valitsemasi arjen kulutus.',
      ),
      numbersTitle: yours,
      numbers: rows.map((item) => ({ label: item.label, display: item.display })),
      check: {
        question: t('Which basket can you plan for?', 'Mihin koriin voit varautua etukäteen?'),
        options: [
          { key: 'regular', text: t('Regular essentials', 'Säännölliset välttämättömät menot') },
          { key: 'irregular', text: t('Irregular must-haves', 'Epäsäännölliset välttämättömät menot') },
          { key: 'neither', text: t('Neither', 'Ei kumpaankaan') },
        ],
        right: 'regular',
        explain: t(
          'Regular essentials come every month at about the same size, so you can plan them; must-haves surprise you.',
          'Säännölliset menot tulevat joka kuukausi suunnilleen samansuuruisina, joten niihin voi varautua; pakolliset yllätykset eivät kysy lupaa.',
        ),
      },
      takeaway: t('Everyday spending is the basket you can adjust fastest.', 'Arjen kulutus on kori, jota voit säätää nopeimmin.'),
    },
    {
      key: 'money-3',
      icon: 'save',
      title: t('How much you can set aside', 'Paljonko voit säästää'),
      teach: t(
        'What you can set aside is what a typical month leaves after bills, essentials and the reserves. It is not your whole balance, so moving it keeps the rest of the month safe.',
        'Säästövara on se, mitä tavallisesta kuukaudesta jää laskujen, perusmenojen ja varausten jälkeen. Se ei ole koko saldosi, joten sen siirtäminen pitää loppukuun turvassa.',
      ),
      numbersTitle: yours,
      numbers: figures(lang, [[{ en: 'You can typically put aside', fi: 'Voit tavallisesti säästää' }, save?.monthly.display]]),
      check: {
        question: t('Where does what you can set aside come from?', 'Mistä säästövara tulee?'),
        options: [
          { key: 'typical', text: t('What a typical month leaves after bills, essentials and reserves', 'Siitä, mitä tavallisesta kuukaudesta jää laskujen, perusmenojen ja varausten jälkeen') },
          { key: 'balance', text: t('Your whole balance', 'Koko saldostasi') },
          { key: 'salary', text: t("Next month's salary", 'Ensi kuun palkasta') },
        ],
        right: 'typical',
        explain: t('It comes from a typical month, after what you must pay, so the rest stays covered.', 'Se tulee tavallisesta kuukaudesta pakollisten menojen jälkeen, joten muu pysyy katettuna.'),
      },
      takeaway: t('Move that amount on payday, and it will not be spent by accident.', 'Siirrä summa palkkapäivänä, niin se ei kulu vahingossa.'),
    },
  ]
}
