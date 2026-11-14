import { useEffect, useState } from 'react'
import { onHandOverWithoutHost } from '../lib/hostNotice.ts'
import { hostStrings } from '../lib/hostStrings.ts'
import { useSettings } from '../lib/settings.ts'

/** How long the notice stays before it closes by itself. */
export const NOTICE_MS = 4000

/**
 * The notice itself. The `role="status"` live region is always rendered, so screen readers
 * announce the text once when it appears. `data-sheet-keep`: an open bottom sheet leaves it live
 * (#440), so a notice over a sheet is tappable and still announced.
 */
export function HostNoticeView({ open, text, onClose }: { open: boolean; text: string; onClose: () => void }) {
  return (
    // Above the composer (88 px over the safe area) and above any open sheet (z-50).
    <div
      data-sheet-keep=""
      className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+88px)] z-[60] mx-auto flex max-w-[480px] justify-center px-4"
    >
      <div role="status" aria-live="polite">
        {open && (
          <button
            type="button"
            onClick={onClose}
            className="pointer-events-auto min-h-11 animate-[sheet-rise_var(--duration-base)_var(--ease-entry)] rounded-lg bg-ink px-4 py-2 text-left text-base font-medium text-surface [box-shadow:var(--shadow-float)] focus-visible:outline-mint"
          >
            {text}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * "This continues in the bank app.": shown when a hand-over found no host (a plain browser).
 * Mounted once at the app root (#431), so it serves every screen and sheet. It closes after a few
 * seconds or on tap. Inside a host (or the demo frame's stub) no event fires, so it never shows.
 */
export function HostNotice() {
  const { lang } = useSettings()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let timer: number | undefined
    const unsubscribe = onHandOverWithoutHost(() => {
      setOpen(true)
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setOpen(false), NOTICE_MS)
    })
    return () => {
      unsubscribe()
      window.clearTimeout(timer)
    }
  }, [])

  return <HostNoticeView open={open} text={hostStrings(lang).continuesInBankApp} onClose={() => setOpen(false)} />
}
