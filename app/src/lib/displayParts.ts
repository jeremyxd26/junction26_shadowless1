// Where a number's `display` may break across lines (#493). The text is never changed: it is only
// cut into parts, so their concatenation is exactly the input. The amount itself, with its sign,
// currency or percent sign and the core's grouping spaces ("1 080,55 €", "€1,080.55", "-€48.80",
// "4,2 %"), is one part that must not break; the rest ("a month", "/ kk") is another. NumberChip
// keeps every part whole and lets a line break only at the space between them.

export interface DisplayPart {
  text: string
  /** True for an amount: rendered with `white-space: nowrap`. */
  amount: boolean
}

const SPACE = '[ \\u00a0\\u202f]'
const AMOUNT = new RegExp(`[-−]?€?\\d(?:[\\d.,]|${SPACE}(?=\\d))*(?:${SPACE}?[€%])?`, 'g')

export function displayParts(display: string): DisplayPart[] {
  const parts: DisplayPart[] = []
  let last = 0
  for (const match of display.matchAll(AMOUNT)) {
    const index = match.index ?? 0
    if (index > last) parts.push({ text: display.slice(last, index), amount: false })
    parts.push({ text: match[0], amount: true })
    last = index + match[0].length
  }
  if (last < display.length) parts.push({ text: display.slice(last), amount: false })
  return parts
}

/**
 * A chip never breaks inside its amount. A chip in running text moves to the next line whole, like a
 * word; only when it is wider than the whole line (200 % text on a narrow screen) does its display
 * wrap between the amount and the words after it ("€3,010.59" | "a month", #726), instead of
 * running past the column. A standalone chip does not shrink below its content in a flex row, and
 * is at most as wide as its container; past that it wraps the same way (DisplayText, #493).
 */
export function chipWrapping(inText: boolean): string {
  return inText ? 'max-w-full text-left' : 'shrink-0 max-w-full text-center'
}

/**
 * The display as unbreakable segments. A new segment starts only after one that ends with a space
 * (the space stays with it), so a break is possible only at a real space between the amount and
 * the words after it: "€780.00 " | "a month". "72nd percentile" or an IBAN "FI21 1234 …" are never
 * cut between letters and digits. Joined, the segments are exactly the display.
 */
export function displaySegments(display: string): string[] {
  const segments: string[] = []
  for (const part of displayParts(display)) {
    const last = segments.length - 1
    if (last >= 0 && !/\s$/.test(segments[last])) {
      // The previous segment has no trailing space: no break here, the part joins it.
      const lead = /^\s*/.exec(part.text)![0]
      if (!lead) {
        segments[last] += part.text
        continue
      }
      segments[last] += lead
      const rest = part.text.slice(lead.length)
      if (rest) segments.push(rest)
      continue
    }
    segments.push(part.text)
  }
  return segments
}
