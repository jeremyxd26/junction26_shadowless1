// "People your age" and "Learn more" in the Learn lessons (#885), from the built finlitLearn.json.
import { describe, expect, it } from 'vitest'
import data from './finlitLearn.json'
import { learnMore, peopleLine } from './peopleLikeYou.ts'

describe('Statistics Finland lines for the persona age band (#885)', () => {
  it('picks the sentence as built from the fact record, for the band, in the language', () => {
    expect(peopleLine('money-1', '35-44', 'en')?.text).toBe(
      'Households headed by someone aged 35–44: €2,362 a month per consumption unit (Statistics Finland, 2022)',
    )
    expect(peopleLine('money-1', '35-44', 'fi')?.text).toBe(
      'Kotitaloudet, joiden viitehenkilö on 35–44-vuotias: 2 362 € kuukaudessa kulutusyksikköä kohden (Tilastokeskus, 2022)',
    )
    expect(peopleLine('saving-2', '35-44', 'en')?.text).toContain('People aged 30–49 in Finland: 32.8%')
    expect(peopleLine('money-2', '35-44', 'fi')?.text).toContain('asuminen vie 30,2 % kulutuksesta')
  })

  it('shows nothing without a band, for an unknown band, or for a lesson without a clean fact', () => {
    expect(peopleLine('money-1', null, 'en')).toBeNull()
    expect(peopleLine('money-1', '0-12', 'en')).toBeNull()
    expect(peopleLine('bills-1', '35-44', 'en')).toBeNull()
    expect(peopleLine('compare-1', '35-44', 'en')).toBeNull()
  })

  it('every lesson with facts covers every adult band; every sentence names its source and year; links are https', () => {
    for (const [lesson, bands] of Object.entries(data.facts)) {
      expect(Object.keys(bands).sort()).toEqual(['18-24', '25-34', '35-44', '45-54', '55-64', '65-74', '75+'])
      for (const entry of Object.values(bands)) {
        expect(entry.en).toMatch(/\(Statistics Finland, 20\d\d\)$/)
        expect(entry.fi).toMatch(/\(Tilastokeskus, 20\d\d\)$/)
        expect(entry.url.en).toMatch(/^https:\/\/stat\.fi\//)
      }
      expect(lesson).toMatch(/^(money|saving)-\d$/)
    }
  })

  it('Learn more: the statistic page when the lesson shows a number, then the topic guide; https only', () => {
    const money = learnMore('money-1', '35-44', 'en')
    expect(money.map((link) => link.title)).toEqual(['The statistic behind this number', 'Keep track of your expenses'])
    expect(money[0].publisher).toBe('Statistics Finland (CC BY 4.0)')
    expect(learnMore('money-3', '35-44', 'fi').map((link) => link.title)).toEqual(['Selvitä menosi'])
    expect(learnMore('bills-1', '35-44', 'en')).toEqual([])
    for (const link of [...money, ...learnMore('saving-2', '35-44', 'fi')]) expect(link.url).toMatch(/^https:\/\//)
  })
})
