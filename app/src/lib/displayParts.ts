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
 * row (like a nowrap chip); only its max width, the container plus 8px of slack that stays inside
 * the card's padding, makes it wrap. So a chip that fitted at normal text size by a hair keeps its
 * one-line look.
 */
export function chipWrapping(inText: boolean): string {
  return inText ? 'whitespace-nowrap' : 'shrink-0 max-w-[calc(100%+8px)] text-center'
}
