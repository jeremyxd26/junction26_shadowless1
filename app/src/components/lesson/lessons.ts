// "Lesson of the day" (#703, #704): what each lesson asks and reveals, from the user's own overview.
// Pure, so the rules run in Node tests. Only the API's `display` strings are shown; no arithmetic on
// `value`, and a right option is known by its source field, never by comparing numbers.
import type { BasketKey, Num, OverviewResponse, SafeToSaveReason } from '../../api/types.ts'
import { isBasketsCard } from '../../lib/changes.ts'
import type { Span } from './lessonStrings.ts'

/** Where an option of a "pick the number" lesson comes from. */
export type PickSource = 'hero' | 'weekly' | 'monthly' | 'essentials'

export interface LessonOption {
  source: PickSource
  number: Num
}

/** Lessons 1 and 3: pick the right number among the user's own. */
export interface PickLesson {
  kind: 'pick'
  id: 1 | 3
  /** Lesson 1: "this week" or "this month", from the period of `hero.primary`. */
  span: Span
  /** The answers, in a fixed order by source (so the right one is not always first), each display once. */
  options: LessonOption[]
  right: LessonOption
  /** Lesson 3: why a typical month leaves nothing (`safe_to_save.reason`), shown in the reveal. */
  reason: SafeToSaveReason | null
}

export interface SplitRow {
  key: BasketKey
  label: string
  /** The basket's share `display`, or its amount `display` when there is no share. */
  display: string
}

/** Lesson 2: which basket takes the biggest part; the reveal shows the split, with no verdict. */
export interface SplitLesson {
  kind: 'split'
  id: 2
  rows: SplitRow[]
}

export type Lesson = PickLesson | SplitLesson

/** Kept for lesson 1's callers and tests. */
export type LessonOneSource = PickSource
export type LessonOne = PickLesson

/** A period that covers a month or more reads "this month"; a shorter one (7 days) "this week". */
export function periodSpan(period: Num['period']): Span {
  const days = (Date.parse(period.end) - Date.parse(period.start)) / 86_400_000
  return days >= 27 ? 'month' : 'week'
}

/** The options in `order`, each display once; when equal displays meet, the right one is kept. */
function pickOptions(order: PickSource[], sources: Partial<Record<PickSource, Num | null>>, right: LessonOption): LessonOption[] {
  const options: LessonOption[] = []
  for (const source of order) {
    const number = sources[source]
    if (!number) continue
    const option = source === right.source ? right : { source, number }
    const same = options.findIndex((shown) => shown.number.display === number.display)
    if (same < 0) options.push(option)
    else if (source === right.source) options[same] = right
  }
  return options
}

/**
 * Lesson 1, "How much can you safely spend this week?". The options are the `display` of
 * `hero.primary` (the right one), `safe_to_save.weekly` and the regular-essentials amount of the
 * overview's baskets card (the source of the opening's basket row). Null (the lesson is hidden)
 * without a hero, or when there is nothing free (`nothing_free`).
 */
export function lessonOne(overview: OverviewResponse | null): PickLesson | null {
  const hero = overview?.hero
  if (!overview || !hero || hero.status === 'nothing_free') return null
  const right: LessonOption = { source: 'hero', number: hero.primary }
  const options = pickOptions(
    ['weekly', 'hero', 'essentials'],
    {
      hero: hero.primary,
      weekly: overview.safe_to_save?.weekly ?? null,
      essentials: overview.cards.find(isBasketsCard)?.items.find((item) => item.key === 'regular_essentials')?.amount ?? null,
    },
    right,
  )
  return { kind: 'pick', id: 1, span: periodSpan(hero.primary.period), options, right, reason: null }
}

/** The three baskets, in the order the opening's basket row shows them. */
const BASKET_KEYS: BasketKey[] = ['regular_essentials', 'unexpected_necessities', 'everyday_spending']

/**
 * Lesson 2, "Which basket takes the biggest part of your money?". The options are the three basket
 * labels of the overview's baskets card; the reveal shows each basket's share (or amount) display.
 * Null without the card or any of the three baskets.
 */
export function lessonTwo(overview: OverviewResponse | null): SplitLesson | null {
  const card = overview?.cards.find(isBasketsCard)
  if (!card) return null
  const rows: SplitRow[] = []
  for (const key of BASKET_KEYS) {
    const item = card.items.find((candidate) => candidate.key === key)
    if (!item) return null
    rows.push({ key, label: item.label, display: (item.share ?? item.amount).display })
  }
  return { kind: 'split', id: 2, rows }
}

/**
 * Lesson 3, "How much can you set aside each week?". The options are the `display` of
 * `safe_to_save.weekly` (the right one), `safe_to_save.monthly` and `hero.primary`. Null without
 * `safe_to_save` or its `weekly`. A `reason` (a typical month leaves nothing) goes into the reveal.
 */
export function lessonThree(overview: OverviewResponse | null): PickLesson | null {
  const save = overview?.safe_to_save
  if (!overview || !save || !save.weekly) return null
  const right: LessonOption = { source: 'weekly', number: save.weekly }
  const options = pickOptions(['monthly', 'weekly', 'hero'], { weekly: save.weekly, monthly: save.monthly, hero: overview.hero?.primary ?? null }, right)
  return { kind: 'pick', id: 3, span: 'week', options, right, reason: save.reason ?? null }
}

/** Today's lessons for this overview, in order; a hidden lesson is left out. */
export function lessonsFor(overview: OverviewResponse | null): Lesson[] {
  return [lessonOne(overview), lessonTwo(overview), lessonThree(overview)].filter((lesson): lesson is Lesson => lesson !== null)
}

/** The lesson's id in the Learn tab's progress ("money-1" …). */
export function lessonKey(lesson: Lesson): string {
  return `money-${lesson.id}`
}

/** The first lesson not done yet, or the first one when all are done (going through again). */
export function startIndex(lessons: Lesson[], done: string[]): number {
  const index = lessons.findIndex((lesson) => !done.includes(lessonKey(lesson)))
  return index < 0 ? 0 : index
}

/** With fewer than two options there is nothing to choose: the lesson opens on its reveal. */
export function opensOnReveal(lesson: Lesson): boolean {
  return lesson.kind === 'pick' && lesson.options.length < 2
}

export interface LessonReveal {
  /** `right` or `close` after a pick; null when the lesson opened on its reveal. */
  verdict: 'right' | 'close' | null
  right: LessonOption
  /** Every other option, to be named by its label. */
  others: LessonOption[]
}

export function revealOf(lesson: PickLesson, picked: PickSource | null): LessonReveal {
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
