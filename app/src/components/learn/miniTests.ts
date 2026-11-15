import type { Language } from '../../api/types.ts'

// Each topic ends with a three-question mini-test (#764 step 3): one right answer each, and a friendly
// one-line explanation shown after a wrong answer. Own short texts, EN and FI; no products or advice.

export interface TestQuestion {
  question: string
  options: { key: string; text: string }[]
  right: string
  /** One friendly line after a wrong answer. */
  explain: string
}

type Bilingual = { en: TestQuestion[]; fi: TestQuestion[] }

const TESTS: Record<string, Bilingual> = {
  money: {
    en: [
      {
        question: 'Which basket is easiest to adjust?',
        options: [
          { key: 'everyday', text: 'Everyday spending' },
          { key: 'regular', text: 'Regular essentials' },
          { key: 'irregular', text: 'Irregular must-haves' },
        ],
        right: 'everyday',
        explain: 'Regular costs and must-haves are hard to change quickly; everyday spending is your own choice.',
      },
      {
        question: 'What has "left to spend" already taken out?',
        options: [
          { key: 'all', text: 'Bills, essentials, a surprise reserve and savings' },
          { key: 'rent', text: 'Only the rent' },
          { key: 'none', text: 'Nothing, it is your balance' },
        ],
        right: 'all',
        explain: 'Left to spend is what remains after bills, essentials, a reserve for surprises and your savings.',
      },
      {
        question: '"Pay yourself first" means…',
        options: [
          { key: 'first', text: 'Saving before spending' },
          { key: 'late', text: 'Paying bills late' },
          { key: 'last', text: 'Saving what is left at the end' },
        ],
        right: 'first',
        explain: 'Saving right after payday, before spending, is what makes it happen.',
      },
    ],
    fi: [
      {
        question: 'Mitä koria on helpointa säätää?',
        options: [
          { key: 'everyday', text: 'Arjen kulutus' },
          { key: 'regular', text: 'Säännölliset menot' },
          { key: 'irregular', text: 'Epäsäännölliset välttämättömät menot' },
        ],
        right: 'everyday',
        explain: 'Säännöllisiä ja pakollisia menoja on vaikea muuttaa nopeasti; arjen kulutuksesta päätät itse.',
      },
      {
        question: 'Mitä käyttövarasta on jo vähennetty?',
        options: [
          { key: 'all', text: 'Laskut, perusmenot, yllätysvaraus ja säästö' },
          { key: 'rent', text: 'Vain vuokra' },
          { key: 'none', text: 'Ei mitään, se on saldosi' },
        ],
        right: 'all',
        explain: 'Käyttövara on se, mitä jää, kun laskut, perusmenot, yllätysvaraus ja säästö on vähennetty.',
      },
      {
        question: '"Maksa ensin itsellesi" tarkoittaa…',
        options: [
          { key: 'first', text: 'Säästämistä ennen kuluttamista' },
          { key: 'late', text: 'Laskujen maksamista myöhässä' },
          { key: 'last', text: 'Sen säästämistä, mitä lopussa jää' },
        ],
        right: 'first',
        explain: 'Kun säästät heti palkkapäivänä, ennen kuluttamista, säästö toteutuu.',
      },
    ],
  },
  bills: {
    en: [
      {
        question: 'A Finnish IBAN starts with…',
        options: [
          { key: 'fi', text: 'FI' },
          { key: 'rf', text: 'RF' },
          { key: 'eu', text: 'EU' },
        ],
        right: 'fi',
        explain: 'Finnish IBANs start with FI and have 18 characters; RF starts some reference numbers.',
      },
      {
        question: 'You pay with a wrong reference number. What can happen?',
        options: [
          { key: 'unmatched', text: 'The payee may not see the bill as paid' },
          { key: 'back', text: 'The money comes back at once' },
          { key: 'nothing', text: 'Nothing at all' },
        ],
        right: 'unmatched',
        explain: 'The money arrives but may not be matched to your bill, so copy the reference exactly.',
      },
      {
        question: 'What is the eräpäivä?',
        options: [
          { key: 'last', text: 'The last day to pay' },
          { key: 'sent', text: 'The day the bill was sent' },
          { key: 'salary', text: 'The day your salary arrives' },
        ],
        right: 'last',
        explain: 'The due date is the last day to pay without a reminder fee or late-payment interest.',
      },
    ],
    fi: [
      {
        question: 'Suomalainen IBAN alkaa kirjaimilla…',
        options: [
          { key: 'fi', text: 'FI' },
          { key: 'rf', text: 'RF' },
          { key: 'eu', text: 'EU' },
        ],
        right: 'fi',
        explain: 'Suomalainen IBAN alkaa kirjaimilla FI ja siinä on 18 merkkiä; RF aloittaa osan viitenumeroista.',
      },
      {
        question: 'Maksat väärällä viitenumerolla. Mitä voi tapahtua?',
        options: [
          { key: 'unmatched', text: 'Laskuttaja ei välttämättä näe laskua maksetuksi' },
          { key: 'back', text: 'Raha palaa heti takaisin' },
          { key: 'nothing', text: 'Ei mitään' },
        ],
        right: 'unmatched',
        explain: 'Raha menee perille, mutta sitä ei ehkä kohdisteta laskuusi, joten kopioi viite tarkasti.',
      },
      {
        question: 'Mikä on eräpäivä?',
        options: [
          { key: 'last', text: 'Viimeinen maksupäivä' },
          { key: 'sent', text: 'Päivä, jolloin lasku lähetettiin' },
          { key: 'salary', text: 'Palkkapäiväsi' },
        ],
        right: 'last',
        explain: 'Eräpäivä on viimeinen päivä maksaa ilman muistutusmaksua tai viivästyskorkoa.',
      },
    ],
  },
  saving: {
    en: [
      {
        question: 'When is saving easiest to turn into a habit?',
        options: [
          { key: 'payday', text: 'Right after payday, automatically' },
          { key: 'end', text: 'When something is left at the end of the month' },
          { key: 'goal', text: 'Only for big goals' },
        ],
        right: 'payday',
        explain: 'An automatic transfer on payday saves before the spending starts.',
      },
      {
        question: 'What is a buffer for?',
        options: [
          { key: 'surprise', text: 'Unexpected must-have costs' },
          { key: 'holiday', text: 'A holiday' },
          { key: 'phone', text: 'A new phone' },
        ],
        right: 'surprise',
        explain: 'A buffer covers surprises such as a repair, so the month stays on track.',
      },
      {
        question: 'A common first goal for a buffer is…',
        options: [
          { key: 'month', text: 'About a month of essential costs' },
          { key: 'day', text: 'One day of spending' },
          { key: 'year', text: 'A full year of income' },
        ],
        right: 'month',
        explain: 'Many start with about a month of essential costs and build it up from there.',
      },
    ],
    fi: [
      {
        question: 'Milloin säästämisestä on helpointa tehdä tapa?',
        options: [
          { key: 'payday', text: 'Heti palkkapäivänä, automaattisesti' },
          { key: 'end', text: 'Kun kuun lopussa jää jotain' },
          { key: 'goal', text: 'Vain isoja tavoitteita varten' },
        ],
        right: 'payday',
        explain: 'Automaattinen siirto palkkapäivänä säästää ennen kuin kuluttaminen alkaa.',
      },
      {
        question: 'Mitä varten puskuri on?',
        options: [
          { key: 'surprise', text: 'Odottamattomia pakollisia menoja varten' },
          { key: 'holiday', text: 'Lomaa varten' },
          { key: 'phone', text: 'Uutta puhelinta varten' },
        ],
        right: 'surprise',
        explain: 'Puskuri kattaa yllätykset, kuten korjauksen, ja kuukausi pysyy raiteillaan.',
      },
      {
        question: 'Tavallinen ensimmäinen tavoite puskurille on…',
        options: [
          { key: 'month', text: 'Noin kuukauden välttämättömät menot' },
          { key: 'day', text: 'Yhden päivän kulutus' },
          { key: 'year', text: 'Koko vuoden tulot' },
        ],
        right: 'month',
        explain: 'Moni aloittaa noin kuukauden välttämättömistä menoista ja kasvattaa puskuria siitä.',
      },
    ],
  },
  compare: {
    en: [
      {
        question: 'Why does Sentti compare you with the median of a group, not the average?',
        options: [
          { key: 'skew', text: 'A few huge purchases skew the average' },
          { key: 'higher', text: 'The median is always higher' },
          { key: 'secret', text: 'The average is kept secret' },
        ],
        right: 'skew',
        explain: 'The median is the person in the middle, so a few very big purchases hardly move it.',
      },
      {
        question: 'Older customers in the dataset tend to have more money coming in. This shows…',
        options: [
          { key: 'link', text: 'A link, not a cause' },
          { key: 'cause', text: 'That age raises income' },
          { key: 'rule', text: 'A rule for everyone' },
        ],
        right: 'link',
        explain: 'Things like work, family and housing can explain both; the data only shows they go together.',
      },
      {
        question: 'Which of these is spending?',
        options: [
          { key: 'groceries', text: 'Groceries' },
          { key: 'invest', text: 'A transfer to your investments' },
          { key: 'sweep', text: 'Moving part of your salary to savings' },
        ],
        right: 'groceries',
        explain: 'Transfers to your own investments or savings stay yours; Sentti keeps them apart from spending.',
      },
    ],
    fi: [
      {
        question: 'Miksi Sentti vertaa sinua ryhmän mediaaniin eikä keskiarvoon?',
        options: [
          { key: 'skew', text: 'Muutama valtava ostos vääristää keskiarvoa' },
          { key: 'higher', text: 'Mediaani on aina suurempi' },
          { key: 'secret', text: 'Keskiarvo on salainen' },
        ],
        right: 'skew',
        explain: 'Mediaani on keskimmäinen ihminen, joten muutama hyvin suuri ostos tuskin liikuttaa sitä.',
      },
      {
        question: 'Aineiston vanhemmilla asiakkailla tulee yleensä enemmän rahaa. Tämä osoittaa…',
        options: [
          { key: 'link', text: 'Yhteyden, ei syytä' },
          { key: 'cause', text: 'Että ikä nostaa tuloja' },
          { key: 'rule', text: 'Säännön kaikille' },
        ],
        right: 'link',
        explain: 'Esimerkiksi työ, perhe ja asuminen voivat selittää molemmat; aineisto näyttää vain, että ne kulkevat yhdessä.',
      },
      {
        question: 'Mikä näistä on kulutusta?',
        options: [
          { key: 'groceries', text: 'Ruokaostokset' },
          { key: 'invest', text: 'Siirto sijoituksiisi' },
          { key: 'sweep', text: 'Osan palkasta siirtäminen säästöön' },
        ],
        right: 'groceries',
        explain: 'Siirrot omiin sijoituksiin tai säästöön ovat yhä sinun; Sentti pitää ne erillään kulutuksesta.',
      },
    ],
  },
}

export function miniTest(topic: string, lang: Language): TestQuestion[] {
  const test = TESTS[topic]
  return test ? test[lang === 'fi' ? 'fi' : 'en'] : []
}
