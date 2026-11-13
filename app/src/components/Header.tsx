import { useRef } from 'react'
import { goBack } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

const LONG_PRESS_MS = 600
const MOVE_TOLERANCE_PX = 10

/**
 * Minimal header inside the host app: back + "Sentti", no logo, no own navigation.
 * A long press anywhere on it opens the demo persona switch.
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
        start.current = { x: event.clientX, y: event.clientY }
        timer.current = window.setTimeout(() => {
          cancel()
          navigator.vibrate?.(10)
          onLongPress()
        }, LONG_PRESS_MS)
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
      <div className="grid min-h-12 grid-cols-[44px_1fr_44px] items-center px-2">
        <button
          type="button"
          onClick={goBack}
          aria-label={t.back}
          className="inline-flex size-11 items-center justify-center rounded-pill text-ink hover:bg-sunken"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.25">
            <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="text-center text-lg font-semibold text-ink">Sentti</h1>
        <span aria-hidden="true" />
      </div>
      <p className="px-4 pb-2 text-center text-xs text-muted">{t.disclosure}</p>
    </header>
  )
}
