/** A window event: the folded opening shows itself whole (before a review card is brought into view). */
export const UNFOLD_OPENING = 'sentti:unfold-opening'

/** The element, if it is laid out (not inside a folded opening or another `hidden` part). */
export function isShown(element: Element): boolean {
  return element.getClientRects().length > 0
}
