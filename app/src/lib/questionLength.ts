// A question is at most 500 characters (contract section 7.1). A paste that would go over is cut
// to fit, at a word break when one is near, and the composer says so (#716).
import { MAX_QUESTION } from './useChat.ts'

/** The composer shows how much room is left once this little is left. */
export const NEAR_LIMIT = 50
/** How far back a cut may go to land on a word break instead of mid-word. */
const WORD_BREAK_REACH = 40

export interface Fitted {
  /** The whole new value of the input. */
  value: string
  /** Where the caret goes: after the inserted text. */
  caret: number
}

/**
 * The input's value after pasting `pasted` over the selection `start`–`end` of `current`, cut to
 * the limit; null when it fits and the browser can paste as usual. Line breaks become spaces, as a
 * one-line field does with them.
 */
export function fitPaste(current: string, start: number, end: number, pasted: string, limit = MAX_QUESTION): Fitted | null {
  const text = pasted.replace(/\s*[\r\n]+\s*/g, ' ')
  const room = limit - (current.length - (end - start))
  if (text.length <= room) return null
  let inserted = text.slice(0, Math.max(0, room))
  // Ends mid-word: go back to the last space if it is close.
  if (inserted.length > 0 && !/\s/.test(text[inserted.length] ?? ' ')) {
    const space = inserted.lastIndexOf(' ')
    if (space > 0 && inserted.length - space <= WORD_BREAK_REACH) inserted = inserted.slice(0, space)
  }
  inserted = inserted.trimEnd()
  return { value: current.slice(0, start) + inserted + current.slice(end), caret: start + inserted.length }
}
