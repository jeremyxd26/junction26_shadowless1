import type { OverviewResponse } from '../../api/types.ts'
import { lessonKey, lessonsFor } from '../lesson/lessons.ts'

// The Learn tab's topics, each a few lessons in the lesson turn's format. Only lessons the persona's
// overview can fill are listed, so a topic never offers an empty lesson.

export interface Topic {
  id: string
  lessons: string[]
}

export function topicsFor(overview: OverviewResponse | null): Topic[] {
  const money = lessonsFor(overview).map(lessonKey)
  return money.length > 0 ? [{ id: 'money', lessons: money }] : []
}

/** The first lesson not done yet, in topic order, or null when every lesson is done. */
export function nextLesson(topics: Topic[], done: string[]): { topic: string; lesson: string } | null {
  for (const topic of topics) {
    const lesson = topic.lessons.find((id) => !done.includes(id))
    if (lesson) return { topic: topic.id, lesson }
  }
  return null
}
