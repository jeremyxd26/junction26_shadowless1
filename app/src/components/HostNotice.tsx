import { useEffect, useState } from 'react'
import { HANDOVER_EVENT } from '../lib/hostActions.ts'
import { hostStrings } from '../lib/hostStrings.ts'
import { useSettings } from '../lib/settings.ts'

/** How long the notice stays before it closes by itself. */
export const NOTICE_MS = 4000

/**
 * "This continues in the bank app.": shown when a hand-over found no host (a plain browser).
 * Fixed above the composer, mounted by its caller. It closes after a few seconds or on tap. The
 * live region is always mounted, so screen readers announce the text once when it appears.
 * `data-sheet-keep`: an open bottom sheet leaves it live (#440), so it is tappable and announced.
 */
export function HostNotice() {
  const { lang } = useSettings()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let timer: number | undefined
    const show = () => {
      setOpen(true)
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setOpen(false), NOTICE_MS)
    }
    window.addEventListener(HANDOVER_EVENT, show)
    return () => {
      window.removeEventListener(HANDOVER_EVENT, show)
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <div
      data-sheet-keep=""
      className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+88px)] z-40 mx-auto flex max-w-[480px] justify-center px-4"
    >
      <div role="status" aria-live="polite">
        {open && (
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="pointer-events-auto min-h-11 animate-[sheet-rise_var(--duration-base)_var(--ease-entry)] rounded-lg bg-ink px-4 py-2 text-left text-base font-medium text-surface [box-shadow:var(--shadow-float)] focus-visible:outline-mint"
          >
            {hostStrings(lang).continuesInBankApp}
          </button>
        )}
      </div>
    </div>
  )
}
