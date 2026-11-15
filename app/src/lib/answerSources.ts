// The sources of a knowledge answer (#922): which of the done event's `sources` are shown as chips.
import type { AnswerSource } from '../api/types.ts'

/** At most this many source chips under an answer. */
export const MAX_SOURCES = 3

/** The sources worth showing: well-formed, https only, deduplicated by url, at most MAX_SOURCES. */
export function shownSources(sources: unknown): AnswerSource[] {
  if (!Array.isArray(sources)) return []
  const seen = new Set<string>()
  const out: AnswerSource[] = []
  for (const item of sources) {
    if (!item || typeof item !== 'object') continue
    const { publisher, title, url, lang } = item as Record<string, unknown>
    if (typeof publisher !== 'string' || !publisher.trim() || typeof url !== 'string' || !/^https:\/\//.test(url)) continue
    if (seen.has(url)) continue
    seen.add(url)
    out.push({ publisher: publisher.trim(), title: typeof title === 'string' ? title.trim() : '', url, lang: lang === 'fi' ? 'fi' : 'en' })
    if (out.length === MAX_SOURCES) break
  }
  return out
}
