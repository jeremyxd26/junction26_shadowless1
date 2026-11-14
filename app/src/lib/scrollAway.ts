/** How far from the bottom of the thread counts as "scrolled up from the latest message". */
const AWAY_PX = 160

/** Whether the page is scrolled up from its bottom by more than AWAY_PX (the scroll-to-latest button). */
export function isAway(scrollY: number, viewport: number, height: number): boolean {
  return height - (scrollY + viewport) > AWAY_PX
}

/** The gap between the scroll-to-latest button and what it sits on (the composer, or a line above it). */
export const ABOVE_COMPOSER_GAP = 11

/**
 * How high above the window's bottom the scroll-to-latest button sits (#762): above the composer's
 * real top, or above anything the composer shows over itself (the mic's status line), whichever is
 * higher, so it is never covered, whatever the text size, the length note or the composer's layout.
 * `formTop` and the rects are the browser's, in viewport px.
 */
export function buttonLift(viewport: number, formTop: number, above: Array<{ top: number; bottom: number; height: number }>): number {
  let top = formTop
  for (const rect of above) {
    if (rect.height > 1 && rect.bottom <= formTop + 1) top = Math.min(top, rect.top)
  }
  return Math.max(0, viewport - top) + ABOVE_COMPOSER_GAP
}
