import type { Language, OverviewResponse } from '../../api/types.ts'
import { lessonKey, lessonsFor, type Lesson } from '../lesson/lessons.ts'
import { billLessons } from './billLessons.ts'

// The Learn tab's topics, each a few lessons in the lesson turn's format. Only lessons the persona's
// overview can fill are listed, so a topic never offers an empty lesson.

export interface Topic {
  id: string
  lessons: string[]
}

/** A topic's lessons, as the lesson turn takes them. */
export function lessonsOf(topic: string, overview: OverviewResponse | null, lang: Language): Lesson[] {
  if (topic === 'bills') return billLessons(lang)
  return lessonsFor(overview)
}

export function topicsFor(overview: OverviewResponse | null, lang: Language = 'en'): Topic[] {
  const topics: Topic[] = []
  const money = lessonsOf('money', overview, lang).map(lessonKey)
  if (money.length > 0) topics.push({ id: 'money', lessons: money })
  topics.push({ id: 'bills', lessons: lessonsOf('bills', overview, lang).map(lessonKey) })
  return topics
}

/** The first lesson not done yet, in topic order, or null when every lesson is done. */
export function nextLesson(topics: Topic[], done: string[]): { topic: string; lesson: string } | null {
  for (const topic of topics) {
    const lesson = topic.lessons.find((id) => !done.includes(id))
    if (lesson) return { topic: topic.id, lesson }
  }
  return null
}

/** A lesson is under way: some lesson is done and some is not (the Learn tab's dot). */
export function unfinished(topics: Topic[], done: string[]): boolean {
  const all = topics.flatMap((topic) => topic.lessons)
  return all.some((id) => done.includes(id)) && all.some((id) => !done.includes(id))
}
