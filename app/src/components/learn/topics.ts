import type { Language, OverviewResponse } from '../../api/types.ts'
import { teachLessons, type TeachLesson } from './teachLessons.ts'

// The Learn tab's topics, each a few lessons taught in four steps (teachLessons.ts). Every topic always
// has its lessons; a lesson whose figure the overview lacks just leaves out its numbers card.

export interface Topic {
  id: string
  lessons: string[]
}

const TOPICS = ['money', 'bills', 'saving', 'compare']

/** A topic's lessons. */
export function lessonsOf(topic: string, overview: OverviewResponse | null, lang: Language): TeachLesson[] {
  return teachLessons(topic, overview, lang)
}

export function topicsFor(overview: OverviewResponse | null, lang: Language = 'en'): Topic[] {
  return TOPICS.map((id) => ({ id, lessons: lessonsOf(id, overview, lang).map((lesson) => lesson.key) }))
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
