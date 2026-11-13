import { useRef } from 'react'
import { goBack } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

const FALLBACK_LONG_PRESS_MS = 600
const MOVE_TOLERANCE_PX = 10

/** `--duration-long-press` from the design tokens, in milliseconds. */
function longPressMs(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--duration-long-press').trim()
  const value = Number.parseFloat(raw)
  if (!Number.isFinite(value) || value <= 0) return FALLBACK_LONG_PRESS_MS
  return raw.endsWith('ms') ? value : raw.endsWith('s') ? value * 1000 : value
}

/**
 * Minimal header inside the host app: back + "Sentti", no logo, no own navigation.
 * A long press on the header (not on the back button) opens the demo persona switch.
 */
export function Header({ onLongPress }: { onLongPress: () => void }) {
  const { t } = useSettings()
  const timer = useRef<number | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)

  const cancel = () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    start.current = null
  }

  return (
    <header
      className="sticky top-0 z-40 bg-page/95 pt-[env(safe-area-inset-top)] backdrop-blur select-none [-webkit-touch-callout:none]"
      onPointerDown={(event) => {
        cancel()
        if (event.target instanceof Element && event.target.closest('button')) return
        start.current = { x: event.clientX, y: event.clientY }
        timer.current = window.setTimeout(() => {
          cancel()
          navigator.vibrate?.(10)
          onLongPress()
        }, longPressMs())
      }}
      onPointerMove={(event) => {
        if (!start.current) return
        const dx = Math.abs(event.clientX - start.current.x)
        const dy = Math.abs(event.clientY - start.current.y)
        if (dx > MOVE_TOLERANCE_PX || dy > MOVE_TOLERANCE_PX) cancel()
      }}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      onContextMenu={(event) => event.preventDefault()}
    >
      <div className="grid min-h-13 grid-cols-[44px_1fr_44px] items-center px-2">
        <button
          type="button"
          onClick={goBack}
          aria-label={t.back}
          className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.25">
            <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="text-center text-lg font-semibold text-ink">Sentti</h1>
        <span aria-hidden="true" />
      </div>
    </header>
  )
}
