import { useCallback, useSyncExternalStore } from 'react'

// Learning progress for the Learn tab (Renat's decision, 14.11 23:05; it overrides #457 for this only):
// kept in the browser's localStorage, one key per demo persona, holding only completed lesson ids, test
// scores and the last lesson. No amounts, no chat text, nothing personal. Every read and write is in
// try/catch, and an in-memory copy keeps the tab working when storage is blocked or missing.

export interface LearnProgress {
  /** Completed lesson ids, such as "money-1". */
  done: string[]
  /** Mini-test scores by topic id: right answers. */
  scores: Record<string, number>
  /** The last lesson opened or completed. */
  last: string | null
}

const EMPTY: LearnProgress = { done: [], scores: {}, last: null }
const PREFIX = 'sentti.learn.'
const memory = new Map<string, LearnProgress>()
const listeners = new Set<() => void>()

/** Only the expected shape survives a read: ids are short strings, scores small numbers. */
export function parseProgress(raw: string | null): LearnProgress {
  if (!raw) return EMPTY
  try {
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object') return EMPTY
    const record = value as Record<string, unknown>
    const done = Array.isArray(record.done)
      ? record.done.filter((id): id is string => typeof id === 'string' && id.length <= 40).slice(0, 100)
      : []
    const scores: Record<string, number> = {}
    if (record.scores && typeof record.scores === 'object') {
      for (const [topic, score] of Object.entries(record.scores as Record<string, unknown>)) {
        if (topic.length <= 40 && typeof score === 'number' && Number.isInteger(score) && score >= 0 && score <= 10) scores[topic] = score
      }
    }
    const last = typeof record.last === 'string' && record.last.length <= 40 ? record.last : null
    return { done: [...new Set(done)], scores, last }
  } catch {
    return EMPTY
  }
}

/** The persona's progress: the in-memory copy, else what storage holds (once), else empty. */
export function readProgress(customerId: string | null): LearnProgress {
  if (!customerId) return EMPTY
  const known = memory.get(customerId)
  if (known) return known
  let raw: string | null
  try {
    raw = window.localStorage.getItem(PREFIX + customerId)
  } catch {
    raw = null
  }
  const progress = parseProgress(raw)
  memory.set(customerId, progress)
  return progress
}

function write(customerId: string, next: LearnProgress | null) {
  memory.set(customerId, next ?? EMPTY)
  try {
    if (next) window.localStorage.setItem(PREFIX + customerId, JSON.stringify(next))
    else window.localStorage.removeItem(PREFIX + customerId)
  } catch {
    // Storage blocked or full: the in-memory copy still serves this visit.
  }
  for (const listener of listeners) listener()
}

/** A lesson is done (its reveal was shown); it becomes the last lesson too. */
export function markDone(customerId: string | null, lessonId: string) {
  if (!customerId) return
  const current = readProgress(customerId)
  if (current.done.includes(lessonId) && current.last === lessonId) return
  write(customerId, { ...current, done: current.done.includes(lessonId) ? current.done : [...current.done, lessonId], last: lessonId })
}

/** A topic's mini-test score (right answers). */
export function saveScore(customerId: string | null, topicId: string, score: number) {
  if (!customerId) return
  const current = readProgress(customerId)
  write(customerId, { ...current, scores: { ...current.scores, [topicId]: score } })
}

/** "Reset progress": the persona starts the Learn tab afresh. */
export function resetProgress(customerId: string | null) {
  if (!customerId) return
  write(customerId, null)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The persona's progress, kept current across the Learn tab and the lesson turns. */
export function useLearnProgress(customerId: string | null): LearnProgress {
  const get = useCallback(() => readProgress(customerId), [customerId])
  return useSyncExternalStore(subscribe, get, get)
}
