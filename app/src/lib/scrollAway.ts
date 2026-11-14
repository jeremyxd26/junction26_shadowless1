/** How far from the bottom of the thread counts as "scrolled up from the latest message". */
const AWAY_PX = 160

/** Whether the page is scrolled up from its bottom by more than AWAY_PX (the scroll-to-latest button). */
export function isAway(scrollY: number, viewport: number, height: number): boolean {
  return height - (scrollY + viewport) > AWAY_PX
}
