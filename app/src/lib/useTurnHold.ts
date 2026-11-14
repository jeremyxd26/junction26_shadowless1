// A client turn's hold (#332). While it holds, what the turn last landed (the turn itself, then
// each step's heading) stays where it landed when something above changes height, for example an
// answer that is still streaming. The reader's position wins: the hold lets go as soon as the
// reader scrolls (a wheel, a touch move, a pointer press, a scroll key) or asks something new, and
// the next step that lands takes it again. It does not lean on the browser's scroll anchoring,
// which loses its anchor when an answer swaps its skeleton for a card (and Safari has none):
// anchoring is off while the hold is on, and the target is the element's own position.
import { useCallback, useEffect, useRef, type RefObject } from 'react'
import { onAsked } from './threadEvents.ts'

/** A landing has finished once the page has not scrolled for this long (or after the cap). */
const STILL_MS = 120
const LANDING_CAP_MS = 2000

/** Keys that scroll the page; in a text field the caret keys only move the caret. */
const SCROLL_KEYS = new Set(['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', ' ', 'Tab'])
const CARET_KEYS = new Set(['Home', 'End', 'ArrowUp', 'ArrowDown', ' '])

interface Hold {
  element: HTMLElement
  /** The element's top in the viewport, in px. */
  top: number
  /** False while a landing still moves the page: a correction then would race the smooth scroll. */
  settled: boolean
}

export function useTurnHold(turn: RefObject<HTMLElement | null>) {
  const hold = useRef<Hold | null>(null)

  const release = useCallback(() => {
    if (!hold.current) return
    hold.current = null
    document.documentElement.style.overflowAnchor = ''
  }, [])

  const correct = useCallback(() => {
    const current = hold.current
    if (!current || !current.settled) return
    if (!current.element.isConnected) return release()
    const moved = current.element.getBoundingClientRect().top - current.top
    if (Math.abs(moved) >= 1) window.scrollTo({ top: window.scrollY + moved, behavior: 'auto' })
  }, [release])

  /**
   * Keep `element` at `top` (viewport px). With `landing`, a scroll is bringing it there: the hold
   * corrects only once the page has been still for a moment, however long the landing takes.
   */
  const arm = useCallback(
    (element: HTMLElement, top: number, landing = false) => {
      const next: Hold = { element, top, settled: !landing }
      hold.current = next
      document.documentElement.style.overflowAnchor = 'none'
      if (!landing) return
      const started = performance.now()
      let timer = 0
      const done = () => {
        window.removeEventListener('scroll', onScroll)
        window.clearTimeout(timer)
        next.settled = true
        if (hold.current === next) correct()
      }
      const onScroll = () => {
        window.clearTimeout(timer)
        if (performance.now() - started > LANDING_CAP_MS) done()
        else timer = window.setTimeout(done, STILL_MS)
      }
      window.addEventListener('scroll', onScroll, { passive: true })
      timer = window.setTimeout(done, STILL_MS)
    },
    [correct],
  )

  useEffect(() => {
    const node = turn.current
    const wrapper = node?.parentElement
    const thread = wrapper?.parentElement
    if (!node || !wrapper || !thread) return
    // Everything above the turn in the thread (the opening, earlier turns), and the turn itself.
    const observer = new ResizeObserver(correct)
    for (const child of thread.children) {
      if (child === wrapper) break
      observer.observe(child)
    }
    observer.observe(node)
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && event.target.matches('input, textarea, select, [contenteditable="true"]')
      if (SCROLL_KEYS.has(event.key) && !(typing && CARET_KEYS.has(event.key))) release()
    }
    const options = { capture: true, passive: true }
    window.addEventListener('wheel', release, options)
    window.addEventListener('touchmove', release, options)
    window.addEventListener('pointerdown', release, options)
    window.addEventListener('keydown', onKey, options)
    const stopAsked = onAsked(release)
    return () => {
      observer.disconnect()
      window.removeEventListener('wheel', release, options)
      window.removeEventListener('touchmove', release, options)
      window.removeEventListener('pointerdown', release, options)
      window.removeEventListener('keydown', onKey, options)
      stopAsked()
      release()
    }
  }, [turn, correct, release])

  return { arm, release }
}
