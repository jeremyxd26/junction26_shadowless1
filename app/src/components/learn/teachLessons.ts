import type { Language, OverviewResponse } from '../../api/types.ts'
import { lessonTwo } from '../lesson/lessons.ts'

// The Learn tab's lessons (#764), each taught in four steps: a short teach card, the customer's own
// numbers (the API's `display`, never formatted here), one check question that is about the idea (its
// options are words, not mixed amounts), and a takeaway. Our own short texts, EN and FI; no products,
// funds, shares or loans. The bills lessons show a sample bill's fields (synthetic data), marked as such.

export type LessonIcon = 'pie' | 'baskets' | 'save' | 'reference' | 'account' | 'auto' | 'payday' | 'buffer' | 'median' | 'link' | 'transfer'

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
  /** Where figures that are not the customer's come from, under the numbers card. */
  source?: string
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

  if (topic === 'compare') {
    // Lessons from the organisers' synthetic dataset (Renat's request): the figures are the dataset's, in our own
    // words, with the source under them; none is the customer's.
    const data = t('In the dataset', 'Aineistossa')
    const source = t(
      'Source: Junction S-Pankki synthetic dataset, 5,100 customers, Oct 2024 – Sep 2026.',
      'Lähde: Junctionin S-Pankki-aineisto (synteettinen), 5 100 asiakasta, lokakuu 2024 – syyskuu 2026.',
    )
    return [
      {
        key: 'compare-1',
        icon: 'median',
        title: t('Median, not average', 'Mediaani, ei keskiarvo'),
        teach: t(
          'When Sentti compares your spending with people like you, it uses the median: the person right in the middle of the group. A few very large purchases can pull an average far up, but they hardly move the middle, so the median shows what is typical.',
          'Kun Sentti vertaa kulutustasi kaltaisiisi, se käyttää mediaania eli ryhmän keskimmäistä ihmistä. Muutama hyvin suuri ostos voi nostaa keskiarvoa paljon, mutta keskikohtaa ne tuskin liikuttavat, joten mediaani kertoo, mikä on tavallista.',
        ),
        numbersTitle: data,
        numbers: [
          { label: t('Customers', 'Asiakkaita'), display: t('5,100', '5 100') },
          { label: t('Middle everyday spending, ages 35–44', 'Arjen kulutuksen mediaani, 35–44-vuotiaat'), display: t('€1,295 a month', '1 295 € / kk') },
        ],
        source,
        check: {
          question: t(
            'One very big purchase lands in a group\'s month. Which figure still shows what is typical?',
            'Ryhmän kuukauteen osuu yksi hyvin suuri ostos. Mikä luku kertoo yhä, mikä on tavallista?',
          ),
          options: [
            { key: 'median', text: t('The median, the middle one', 'Mediaani eli keskimmäinen') },
            { key: 'average', text: t('The average', 'Keskiarvo') },
            { key: 'largest', text: t('The largest purchase', 'Suurin ostos') },
          ],
          right: 'median',
          explain: t(
            'The big purchase pulls the average up; the person in the middle stays where they were.',
            'Suuri ostos nostaa keskiarvoa; keskimmäinen ihminen pysyy paikallaan.',
          ),
        },
        takeaway: t(
          'When you compare yourself with others, look for the median, and treat it as a guide, not a target.',
          'Kun vertaat itseäsi muihin, katso mediaania ja pidä sitä suuntana, ei tavoitteena.',
        ),
      },
      {
        key: 'compare-2',
        icon: 'link',
        title: t('A link is not a cause', 'Yhteys ei ole syy'),
        teach: t(
          'In this synthetic dataset, older customers tend to have more money coming in each month: the link is moderate. That does not mean age causes it; income, work, family and housing all play a part.',
          'Tässä synteettisessä aineistossa vanhemmilla asiakkailla tulee usein enemmän rahaa kuukaudessa: yhteys on kohtalainen. Se ei tarkoita, että ikä aiheuttaisi sen; myös tulot, työ, perhe ja asuminen vaikuttavat.',
        ),
        numbersTitle: data,
        numbers: [
          { label: t('Age and money coming in', 'Ikä ja tuleva raha'), display: t('ρ ≈ 0.47, moderate', 'ρ ≈ 0,47, kohtalainen') },
          { label: t('Age and how often people pay', 'Ikä ja maksujen määrä'), display: t('ρ ≈ 0.03, almost none', 'ρ ≈ 0,03, lähes olematon') },
        ],
        source,
        check: {
          question: t(
            'Older customers in the dataset have more money coming in. What can you say?',
            'Aineiston vanhemmilla asiakkailla tulee enemmän rahaa. Mitä siitä voi sanoa?',
          ),
          options: [
            { key: 'link', text: t('The two go together, but age is not shown to be the cause', 'Ne kulkevat yhdessä, mutta iän ei ole osoitettu olevan syy') },
            { key: 'cause', text: t('Getting older raises your income', 'Vanheneminen nostaa tulojasi') },
            { key: 'young', text: t('Young people spend too much', 'Nuoret kuluttavat liikaa') },
          ],
          right: 'link',
          explain: t(
            'A link only says that two things move together; other things, like work and family, can explain both.',
            'Yhteys kertoo vain, että kaksi asiaa kulkee yhdessä; muut asiat, kuten työ ja perhe, voivat selittää molemmat.',
          ),
        },
        takeaway: t(
          'When two things move together, ask what else could explain it before you draw a conclusion.',
          'Kun kaksi asiaa kulkee yhdessä, kysy, mikä muu voisi selittää sen, ennen kuin teet johtopäätöksen.',
        ),
      },
      {
        key: 'compare-3',
        icon: 'transfer',
        title: t('Spending or moving money', 'Kulutus vai rahan siirto'),
        teach: t(
          'Not every euro that leaves your account is spending. Money you move to your investments or to savings is still yours, so Sentti keeps these transfers apart from what you spend.',
          'Kaikki tililtä lähtevä raha ei ole kulutusta. Sijoituksiin tai säästöön siirtämäsi raha on yhä sinun, joten Sentti pitää nämä siirrot erillään kulutuksesta.',
        ),
        numbersTitle: data,
        numbers: [
          {
            label: t('Moves to investments and savings, all customers', 'Siirrot sijoituksiin ja säästöön, kaikki asiakkaat'),
            display: t('about €36 million', 'noin 36 milj. €'),
          },
        ],
        source,
        check: {
          question: t('You move money from your account to your savings. Is it spending?', 'Siirrät rahaa tililtäsi säästöön. Onko se kulutusta?'),
          options: [
            { key: 'no', text: t('No, the money is still yours', 'Ei, raha on yhä sinun') },
            { key: 'yes', text: t('Yes, it left the account', 'Kyllä, se lähti tililtä') },
            { key: 'month', text: t('Only at the end of the month', 'Vain kuun lopussa') },
          ],
          right: 'no',
          explain: t(
            'Moving money between your own pots is not spending; Sentti counts what you buy and pay.',
            'Rahan siirtäminen omien varojesi välillä ei ole kulutusta; Sentti laskee sen, mitä ostat ja maksat.',
          ),
        },
        takeaway: t(
          'Look at your spending without your own transfers, and your picture of the month stays true.',
          'Katso kulutustasi ilman omia siirtojasi, niin kuva kuukaudesta pysyy oikeana.',
        ),
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
