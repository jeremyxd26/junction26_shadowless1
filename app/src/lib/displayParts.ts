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
 * Chips in running text never wrap. A standalone chip does not shrink below its content in a flex
 * row (like a nowrap chip), and is at most as wide as its container; past that its display wraps
 * between the amount and the words after it (DisplayText). A chip whose text used to spill into
 * its own padding, hidden by nowrap, now wraps instead (#493).
 */
export function chipWrapping(inText: boolean): string {
  return inText ? 'whitespace-nowrap' : 'shrink-0 max-w-full text-center'
}

/**
 * The display as unbreakable segments: each part with the spaces that follow it, so the only break
 * is between the amount and the words after it. Joined, they are exactly the display.
 */
export function displaySegments(display: string): string[] {
  const segments: string[] = []
  for (const part of displayParts(display)) {
    const lead = /^\s*/.exec(part.text)![0]
    const rest = part.text.slice(lead.length)
    if (segments.length > 0) segments[segments.length - 1] += lead
    else if (lead) segments.push(lead)
    if (rest) {
      if (segments.length === 1 && segments[0] === lead && lead) segments[0] += rest
      else segments.push(rest)
    }
  }
  return segments
}
