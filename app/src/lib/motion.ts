import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Num } from '../api/types.ts'

const REDUCE = '(prefers-reduced-motion: reduce)'

function subscribe(onChange: () => void) {
  const query = window.matchMedia(REDUCE)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** True when the customer asked for less motion: no flight and no counting, only a short cross-fade. */
export function usePrefersReducedMotion(): boolean {
  // The server snapshot (no motion preference known) only matters when rendering to a string, as in
  // tests; the browser always reads the media query.
  return useSyncExternalStore(subscribe, () => window.matchMedia(REDUCE).matches, () => false)
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia(REDUCE).matches
}

/** Reads a design token (for example `--duration-money`) as milliseconds or as a colour string. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/**
 * A duration token in milliseconds. The token file says `600ms`, but the CSS minifier of the
 * build rewrites it to `.6s`, so both units are read; anything else gives `fallback`.
 */
export function tokenMs(name: string, fallback: number): number {
  return parseDuration(token(name), fallback)
}

export function parseDuration(value: string, fallback: number): number {
  const match = /^(\d*\.?\d+)(ms|s)?$/.exec(value.trim())
  if (!match) return fallback
  const amount = Number(match[1])
  if (!Number.isFinite(amount)) return fallback
  return match[2] === 's' ? amount * 1000 : amount
}

const NUMBER = /\d(?:[\d\s\u00a0\u202f.,']*\d)?/

/**
 * An in-between frame of a counter, written like `display`: same prefix, suffix, decimal and
 * group separators ("€1,080.42 a month", or "1 080,42 €" with a no-break space). Only for animation frames; the last
 * frame is always the API's `display` string itself.
 */
export function formatLike(display: string, value: number): string {
  const match = NUMBER.exec(display)
  if (!match) return display
  const raw = match[0]
  const fraction = /[.,](\d{1,2})$/.exec(raw)
  const decimals = fraction ? fraction[1].length : 0
  const decimalSeparator = fraction ? raw[raw.length - decimals - 1] : ''
  const whole = fraction ? raw.slice(0, raw.length - decimals - 1) : raw
  const groupSeparator = /\D/.exec(whole)?.[0] ?? (decimalSeparator === ',' ? '\u00a0' : ',')
  const [integer, cents] = Math.abs(value).toFixed(decimals).split('.')
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, groupSeparator)
  const body = cents ? `${grouped}${decimalSeparator}${cents}` : grouped
  return display.slice(0, match.index) + body + display.slice(match.index + raw.length)
}

/** A counter run: count from `from` to the shown number. `run: false` holds `from` until the run starts. */
export interface Count {
  seq: number
  from: Num
  run: boolean
}

/**
 * The text of a number that may be counting. Without a count (or with reduced motion) it is
 * `to.display`. While a count runs it is an eased in-between frame, and it ends on `to.display`.
 */
export function useCountedText(to: Num, count: Count | undefined, duration: number): string {
  const reduced = usePrefersReducedMotion()
  const [frame, setFrame] = useState<{ seq: number; text: string } | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const seq = count?.seq
  const run = count?.run ?? false
  const from = count?.from.value
  const moves = count !== undefined && !reduced && from !== to.value

  useEffect(() => {
    if (!moves || !run || seq === undefined || from === undefined) return
    // The clock starts at the first frame, and progress stays within [0, 1], so every frame lies
    // between the old and the new value (a frame time can be earlier than performance.now()).
    let start: number | null = null
    let raf = 0
    const step = (now: number) => {
      if (start === null) start = now
      const t = duration > 0 ? Math.min(1, Math.max(0, (now - start) / duration)) : 1
      if (t >= 1) {
        setFrame(null)
        setDone(seq)
        return
      }
      const eased = 1 - (1 - t) ** 3
      setFrame({ seq, text: formatLike(to.display, from + (to.value - from) * eased) })
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [moves, run, seq, from, to.value, to.display, duration])

  if (!moves || !count || done === count.seq) return to.display
  if (frame?.seq === count.seq) return frame.text
  return count.from.display
}
