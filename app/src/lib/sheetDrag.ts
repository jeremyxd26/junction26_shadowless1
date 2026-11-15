import { useEffect, useRef, type RefObject } from 'react'
import { prefersReducedMotion } from './motion.ts'

// Drag a bottom sheet down to close it (Renat: the sheets felt dead). The sheet follows the finger 1:1 downward, with
// a rubber band upward, and the backdrop fades with it. On release it closes when dragged past DISMISS_SHARE of its
// height or flicked down faster than FLICK_PX_PER_MS, sliding out; otherwise it springs back. Escape and the close
// button stay; with reduced motion it snaps back or closes at once.

/** Dragged past this share of the sheet's height, the release closes it. */
export const DISMISS_SHARE = 0.3
/** A flick down faster than this (px per ms) closes it whatever the distance. */
export const FLICK_PX_PER_MS = 0.5
/** A move shorter than this is a tap, not a drag yet. */
const SLOP_PX = 6
/** The velocity is read over the last stretch of the drag. */
const VELOCITY_WINDOW_MS = 100
/** The most the sheet moves up against the rubber band. */
const RUBBER_MAX_PX = 40

/** Where the sheet sits for a finger `dy` px below where it started: 1:1 down, with resistance up. */
export function rubberBand(dy: number): number {
  if (dy >= 0) return dy
  const up = -dy
  return -(RUBBER_MAX_PX * up) / (up + 2 * RUBBER_MAX_PX)
}

/** Whether a release `dy` px down, at `velocity` px per ms (down positive), closes a sheet `height` px tall. */
export function shouldDismiss(dy: number, height: number, velocity: number): boolean {
  return dy > 0 && (dy > height * DISMISS_SHARE || velocity > FLICK_PX_PER_MS)
}

/**
 * Whether `target` sits in something scrolled away from its top, up to and including `panel`. Then a downward move
 * scrolls that content back up, and no drag starts: no accidental closing while reading a long sheet.
 */
export function scrolledDown(target: Element | null, panel: Element): boolean {
  for (let node = target; node; node = node.parentElement) {
    if (node.scrollTop > 0) return true
    if (node === panel) return false
  }
  return false
}

/** Whether `target` sits in a row that scrolls sideways (a chip row): there a move claims nothing before the slop. */
function inSidewaysScroller(target: Element | null, panel: Element): boolean {
  for (let node = target; node && node !== panel; node = node.parentElement) {
    if (node.scrollWidth > node.clientWidth && /(auto|scroll)/.test(getComputedStyle(node).overflowX)) return true
  }
  return false
}

function durationMs(name: string, fallback: number): number {
  const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

interface Sample {
  y: number
  t: number
}

/**
 * Lets the sheet `panel` be dragged down to close (`onDismiss`), its backdrop `scrim` fading with it. Touch drags
 * start anywhere on the sheet whose content is at its top; mouse and pen drags start on an element marked
 * `data-sheet-handle` (the grabber and the title row), so selecting text in the content still works.
 */
export function useSheetDrag(
  panel: RefObject<HTMLElement | null>,
  scrim: RefObject<HTMLElement | null>,
  onDismiss: () => void,
): void {
  const dismiss = useRef(onDismiss)
  useEffect(() => {
    dismiss.current = onDismiss
  }, [onDismiss])

  useEffect(() => {
    const sheet = panel.current
    if (!sheet) return
    let start: (Sample & { x: number; early: boolean }) | null = null // a gesture that may become a drag
    let pointerId: number | null = null // the mouse or pen pointer of the gesture, if not touch
    let dragging = false
    let dy = 0
    let samples: Sample[] = []
    let closing = false
    let swallowClick = false

    const place = (offset: number, sheetTransition: string, scrimTransition: string) => {
      sheet.style.transition = sheetTransition
      sheet.style.transform = offset ? `translateY(${offset}px)` : ''
      const backdrop = scrim.current
      if (!backdrop) return
      backdrop.style.transition = scrimTransition
      const share = Math.min(Math.max(offset / Math.max(sheet.offsetHeight, 1), 0), 1)
      backdrop.style.opacity = offset > 0 ? String(1 - share) : ''
    }

    const begin = (x: number, y: number, t: number, early: boolean) => {
      if (closing) return
      start = { x, y, t, early }
      dragging = false
      dy = 0
      samples = [{ y, t }]
    }

    /** True when the move is the sheet's (the caller then stops the page from scrolling). */
    const move = (x: number, y: number, t: number): boolean => {
      if (!start || closing) return false
      const down = y - start.y
      const sideways = x - start.x
      if (!dragging) {
        // Up or sideways first: the content scrolls, and this gesture never drags.
        if (down < 0 || Math.abs(sideways) > Math.abs(down)) {
          if (Math.abs(down) >= SLOP_PX || Math.abs(sideways) >= SLOP_PX) start = null
          return false
        }
        if (down < SLOP_PX) return start.early && down > 0 // claim a downward start early, before the page scrolls
        dragging = true
        sheet.style.animation = 'none' // the opening spring would hold the transform
      }
      dy = down
      samples.push({ y, t })
      while (samples.length > 2 && t - samples[0].t > VELOCITY_WINDOW_MS) samples.shift()
      place(rubberBand(dy), 'none', 'none')
      return true
    }

    const end = (cancelled: boolean) => {
      if (!start) return
      start = null
      pointerId = null
      if (!dragging) return
      dragging = false
      swallowClick = true // the click that may follow a mouse drag is not a tap on what was under it
      window.setTimeout(() => (swallowClick = false), 0)
      const first = samples[0]
      const last = samples[samples.length - 1]
      const velocity = last.t > first.t ? (last.y - first.y) / (last.t - first.t) : 0
      const reduced = prefersReducedMotion()
      if (!cancelled && shouldDismiss(dy, sheet.offsetHeight, velocity)) {
        closing = true
        const ms = reduced ? 0 : durationMs('--duration-base', 250)
        const ease = 'var(--ease-exit)'
        place(sheet.offsetHeight + 24, reduced ? 'none' : `transform ${ms}ms ${ease}`, reduced ? 'none' : `opacity ${ms}ms ${ease}`)
        window.setTimeout(() => dismiss.current(), ms)
        return
      }
      const ms = reduced ? 0 : durationMs('--duration-base', 250) * 1.5
      place(0, reduced ? 'none' : `transform ${ms}ms var(--ease-spring)`, reduced ? 'none' : `opacity ${ms}ms var(--ease-entry)`)
    }

    // Touch: anywhere on the sheet, unless the touch is in content scrolled away from its top.
    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) return end(true)
      const target = event.target instanceof Element ? event.target : null
      if (scrolledDown(target, sheet)) return
      const touch = event.touches[0]
      begin(touch.clientX, touch.clientY, event.timeStamp, !inSidewaysScroller(target, sheet))
    }
    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) return end(true)
      const touch = event.touches[0]
      if (move(touch.clientX, touch.clientY, event.timeStamp) && event.cancelable) event.preventDefault()
    }
    const onTouchEnd = () => end(false)
    const onTouchCancel = () => end(true)

    // Mouse and pen: on the grabber and the title row only.
    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType === 'touch' || event.button !== 0) return
      const target = event.target instanceof Element ? event.target : null
      if (!target?.closest('[data-sheet-handle]')) return
      pointerId = event.pointerId
      begin(event.clientX, event.clientY, event.timeStamp, true)
    }
    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerId !== pointerId) return
      if (move(event.clientX, event.clientY, event.timeStamp)) event.preventDefault()
    }
    const onPointerUp = (event: PointerEvent) => {
      if (event.pointerId === pointerId) end(event.type === 'pointercancel')
    }
    const onClick = (event: MouseEvent) => {
      if (!swallowClick) return
      event.preventDefault()
      event.stopPropagation()
    }

    sheet.addEventListener('touchstart', onTouchStart, { passive: true })
    sheet.addEventListener('touchmove', onTouchMove, { passive: false })
    sheet.addEventListener('touchend', onTouchEnd)
    sheet.addEventListener('touchcancel', onTouchCancel)
    sheet.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerUp)
    sheet.addEventListener('click', onClick, true)
    return () => {
      sheet.removeEventListener('touchstart', onTouchStart)
      sheet.removeEventListener('touchmove', onTouchMove)
      sheet.removeEventListener('touchend', onTouchEnd)
      sheet.removeEventListener('touchcancel', onTouchCancel)
      sheet.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onPointerUp)
      sheet.removeEventListener('click', onClick, true)
    }
  }, [panel, scrim])
}
