import { useEffect, useState } from 'react'
import { usePrefersReducedMotion } from './motion.ts'

// The typing reveal of an answer (#686): a text that arrives in front of the customer appears word by word,
// the whole of it in at most REVEAL_MAX_MS, whatever its length. Client-side only: the service still sends
// the finished, validated text; nothing here changes a number or a word.

/** The longest reveal of one text. */
export const REVEAL_MAX_MS = 1000
/** One step of the reveal. */
export const REVEAL_TICK_MS = 30

/** The end offset of each word (a run of non-space characters) of a text. */
export function wordEnds(text: string): number[] {
  const ends: number[] = []
  for (const match of text.matchAll(/\S+/g)) ends.push((match.index ?? 0) + match[0].length)
  return ends
}

/** The first `count` words of a text, cut only at the end of a word, so a {{nK}} token is never split. */
export function firstWords(text: string, count: number): string {
  if (!Number.isFinite(count)) return text
  const ends = wordEnds(text)
  if (count >= ends.length) return text
  return count <= 0 ? '' : text.slice(0, ends[count - 1])
}

/** Words per step: `total` words take at most REVEAL_MAX_MS; a short text goes one word a step. */
export function revealStep(total: number): number {
  return Math.max(1, Math.ceil((total * REVEAL_TICK_MS) / REVEAL_MAX_MS))
}

/** How many words to show: every word, unless a reveal runs (a live answer, motion allowed, not skipped). */
export function wordsToShow(
  shown: number,
  { live, reduced, skipped }: { live: boolean; reduced: boolean; skipped: boolean },
): number {
  return live && !reduced && !skipped ? shown : Number.POSITIVE_INFINITY
}

/** About how long the rest of a reveal takes, for a card that should fade in after the text. */
export function remainingMs(words: number, total: number): number {
  if (!Number.isFinite(words) || words >= total) return 0
  return Math.ceil((total - words) / revealStep(total)) * REVEAL_TICK_MS
}

/**
 * Whether a live answer's cards wait behind the skeleton: while the answer streams and while its text types
 * in, so the numbers never show before the words. A reveal that is off (history, reduced motion, a tap)
 * shows every word (`words` is Infinity) and never holds the cards.
 */
export function holdsCards(words: number, { streaming, revealing }: { streaming: boolean; revealing: boolean }): boolean {
  return Number.isFinite(words) && (streaming || revealing)
}

export interface Reveal {
  /** How many words of the text to show (Infinity: all). */
  words: number
  revealing: boolean
  skipped: boolean
  /** Show everything at once (a tap on the answer). */
  skip: () => void
}

/**
 * The word reveal of one answer. `live` is fixed when the turn mounts: an answer that started in front of
 * the customer reveals; one from history (already finished when it mounts) never does. The count chases the
 * text as it grows, so a streamed text and a text that arrives at once with `done` both type in.
 */
export function useWordReveal(text: string, live: boolean): Reveal {
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(0)
  const [skipped, setSkipped] = useState(false)
  const total = wordEnds(text).length
  const words = wordsToShow(shown, { live, reduced, skipped })
  const revealing = words < total
  useEffect(() => {
    if (!revealing) return
    const id = window.setTimeout(() => setShown((n) => Math.min(total, n + revealStep(total))), REVEAL_TICK_MS)
    return () => window.clearTimeout(id)
  }, [revealing, shown, total])
  return { words, revealing, skipped, skip: () => setSkipped(true) }
}
