// The core joins the parts of a date with no-break spaces, so "28 September 2026" never splits
// across lines (#662). At 200 % text such a run can be wider than its card, and a no-break run that
// cannot fit scrolls the page sideways (#725). The app shows each run as one box with ordinary
// spaces: it moves to the next line whole while it fits, exactly as before, and only when it is
// wider than the line does it wrap inside, at its own spaces, never in the middle of a word.

/** A run of words the API joined with no-break spaces. */
const JOINED = /[^\s]+(?:\u00a0+[^\s]+)+/g

/** `text` split into plain parts and runs to keep together (their no-break spaces made ordinary). */
export function splitKeepTogether(text: string): Array<string | { together: string }> {
  const out: Array<string | { together: string }> = []
  let last = 0
  for (const match of text.matchAll(JOINED)) {
    const index = match.index ?? 0
    if (index > last) out.push(text.slice(last, index))
    out.push({ together: match[0].replace(/\u00a0+/g, ' ') })
    last = index + match[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
