// "Lesson of the day" (#703): what a lesson asks and reveals, from the user's own overview. Pure, so
// the rules run in Node tests. Only the API's `display` strings are shown; no arithmetic on `value`,
// and the right option is known by its source field, never by comparing numbers.
import type { Num, OverviewResponse } from '../../api/types.ts'
import { isBasketsCard } from '../../lib/changes.ts'
import type { Span } from './lessonStrings.ts'

/** Where an option of lesson 1 comes from. `hero` (safe to spend) is the right one. */
export type LessonOneSource = 'hero' | 'weekly' | 'essentials'

export interface LessonOption {
  source: LessonOneSource
  number: Num
}

export interface LessonOne {
  /** "this week" or "this month", from the period of `hero.primary`. */
  span: Span
  /** The answers, in a fixed order by source (so the right one is not always first), each display once. */
  options: LessonOption[]
  right: LessonOption
}

/** The answers' order, by source. */
const ORDER: LessonOneSource[] = ['weekly', 'hero', 'essentials']

/** A period that covers a month or more reads "this month"; a shorter one (7 days) "this week". */
export function periodSpan(period: Num['period']): Span {
  const days = (Date.parse(period.end) - Date.parse(period.start)) / 86_400_000
  return days >= 27 ? 'month' : 'week'
}

/**
 * Lesson 1, "How much can you safely spend this week?". The options are the `display` of
 * `hero.primary` (the right one), `safe_to_save.weekly` and the regular-essentials amount of the
 * overview's baskets card (the source of the opening's basket row). Null (the lesson is hidden)
 * without a hero, or when there is nothing free (`nothing_free`).
 */
export function lessonOne(overview: OverviewResponse | null): LessonOne | null {
  const hero = overview?.hero
  if (!overview || !hero || hero.status === 'nothing_free') return null
  const right: LessonOption = { source: 'hero', number: hero.primary }
  const sources: Record<LessonOneSource, Num | null> = {
    hero: hero.primary,
    weekly: overview.safe_to_save?.weekly ?? null,
    essentials: overview.cards.find(isBasketsCard)?.items.find((item) => item.key === 'regular_essentials')?.amount ?? null,
  }
  const options: LessonOption[] = []
  for (const source of ORDER) {
    const number = sources[source]
    if (!number) continue
    const option = source === 'hero' ? right : { source, number }
    // Equal displays show once; when one of them is the right answer, it is the one kept.
    const same = options.findIndex((shown) => shown.number.display === number.display)
    if (same < 0) options.push(option)
    else if (source === 'hero') options[same] = right
  }
  return { span: periodSpan(hero.primary.period), options, right }
}

/** With fewer than two options there is nothing to choose: the lesson opens on its reveal. */
export function opensOnReveal(lesson: LessonOne): boolean {
  return lesson.options.length < 2
}

export interface LessonReveal {
  /** `right` or `close` after a pick; null when the lesson opened on its reveal. */
  verdict: 'right' | 'close' | null
  right: LessonOption
  /** Every other option, to be named by its label. */
  others: LessonOption[]
}

export function revealOf(lesson: LessonOne, picked: LessonOneSource | null): LessonReveal {
  return {
    verdict: picked === null ? null : picked === lesson.right.source ? 'right' : 'close',
    right: lesson.right,
    others: lesson.options.filter((option) => option.source !== lesson.right.source),
  }
}

/**
 * A label inside a sentence ("€83.78 a week is typically left each week."): the first letter goes
 * lower case unless the label starts with an acronym or a name such as "S-Bonus".
 */
export function inSentence(label: string): string {
  const [first, second] = label
  if (!first || !second || !/\p{Ll}/u.test(second)) return label
  return first.toLowerCase() + label.slice(1)
}
