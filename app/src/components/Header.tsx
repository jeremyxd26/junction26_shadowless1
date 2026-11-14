import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { canGoBack, goBack, useUrl } from '../lib/url.ts'
import { showPersonaButton } from '../lib/hostBridge.ts'
import { hostStrings } from '../lib/hostStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { BottomSheet } from './BottomSheet.tsx'

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
 * Minimal header inside the host app: back, "Sentti" with a small AI tag, and ⓘ, which opens the
 * AI disclosure (`ai_disclosure`) in a small sheet. No logo and no own navigation.
 * A long press on the header (not on a button) opens the demo persona switch. In a plain browser,
 * where nobody would guess the long press, a visible button in the left cell opens it too, unless
 * the back chevron takes that cell.
 */
export function Header({ onLongPress, disclosure }: { onLongPress: () => void; disclosure: string }) {
  const { t, lang } = useSettings()
  const [about, setAbout] = useState(false)
  // Re-render on every navigation, so the back button follows the current screen.
  useUrl()
  const showBack = canGoBack()
  const showPersonas = showPersonaButton(undefined, showBack)
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
        {showBack ? (
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
        ) : showPersonas ? (
          // First screen in a plain browser: nowhere to go back to, so the cell opens the demo personas.
          <button
            type="button"
            onClick={onLongPress}
            aria-label={hostStrings(lang).personas}
            className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="8" r="3.5" />
              <path d="M5 19.5c1.2-3.4 3.9-5 7-5s5.8 1.6 7 5" strokeLinecap="round" />
            </svg>
          </button>
        ) : (
          // Inside a host with nowhere to go back to (not reached today); the cell keeps the title centred.
          <span aria-hidden="true" />
        )}
        <h1 className="flex items-center justify-center gap-1.5 text-lg font-semibold text-ink">
          Sentti
          <span className="rounded-sm border border-brand px-1 text-xs font-bold leading-4 text-brand">AI</span>
        </h1>
        <button
          type="button"
          onClick={() => setAbout(true)}
          aria-label={t.aboutSentti}
          className="inline-flex size-11 items-center justify-center rounded-pill text-brand hover:bg-sunken"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {/* In a portal: the header's backdrop blur would pin a fixed sheet to the header. */}
      {about &&
        createPortal(
          <BottomSheet title={t.aboutSentti} onClose={() => setAbout(false)}>
            <p className="text-base text-ink-2">{disclosure}</p>
          </BottomSheet>,
          document.body,
        )}
    </header>
  )
}
