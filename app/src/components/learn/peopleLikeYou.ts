import type { Language } from '../../api/types.ts'
import data from './finlitLearn.json'

// "People your age" lines and "Learn more" links for the Learn lessons (#885), from finlitLearn.json, which
// scripts/build_finlit_learn.py writes from the finlit corpus (Statistics Finland numbers by age, official source
// cards). The sentences are written there from each fact's own fields; this file only picks one, never computes.

interface FactEntry {
  id: string
  en: string
  fi: string
  url: { en: string; fi: string }
}

interface MoreCard {
  title: { en: string; fi: string }
  publisher: string
  url: { en: string; fi: string }
}

const FACTS = data.facts as Record<string, Record<string, FactEntry>>
const MORE = data.more as Record<string, MoreCard[]>
const SOURCE = data.source as { en: string; fi: string }

export interface PeopleLine {
  text: string
  /** The statistic's page on stat.fi. */
  url: string
}

export interface MoreLink {
  title: string
  publisher: string
  url: string
}

/** The Statistics Finland line for this lesson and the persona's age band, or null (no band, or no clean fact). */
export function peopleLine(lessonKey: string, band: string | null | undefined, lang: Language): PeopleLine | null {
  const entry = band ? FACTS[lessonKey]?.[band] : undefined
  return entry ? { text: entry[lang], url: entry.url[lang] } : null
}

/** "Learn more": the statistic's page when the lesson shows a number for the band, then the topic's guide. */
export function learnMore(lessonKey: string, band: string | null | undefined, lang: Language): MoreLink[] {
  const links: MoreLink[] = []
  const line = peopleLine(lessonKey, band, lang)
  if (line) links.push({ title: lang === 'fi' ? 'Tilasto luvun takana' : 'The statistic behind this number', publisher: SOURCE[lang], url: line.url })
  const topic = lessonKey.split('-')[0]
  for (const card of MORE[topic] ?? []) links.push({ title: card.title[lang], publisher: card.publisher, url: card.url[lang] })
  return links
}
