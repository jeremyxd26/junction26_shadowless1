// Where the thread brings a new turn or a client turn's new step (#332): just below the sticky
// header, measured, so it is not hidden under a header that grows with large text (at 200 % text
// the header is 176 px tall, while a `scroll-margin` of 4rem is 128 px).

/** The gap between the header and what lands under it; at normal text this keeps the old 64 px. */
const GAP_PX = 12

/** The bottom edge of the app's sticky header in the viewport (0 without one). */
export function headerBottom(): number {
  return document.querySelector('header')?.getBoundingClientRect().bottom ?? 0
}

/** Where a landed element's top sits in the viewport. */
export function landingTop(): number {
  return headerBottom() + GAP_PX
}

/** Scrolls the page so `element` starts just below the header. */
export function landBelowHeader(element: Element, smooth: boolean) {
  const top = window.scrollY + element.getBoundingClientRect().top - landingTop()
  window.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' })
}
