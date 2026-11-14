import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { FOCUSABLE, escapeCloses, trapTarget } from '../lib/focusTrap.ts'
import { openSheet } from '../lib/sheetStack.ts'
import { useSettings } from '../lib/settings.ts'

function focusableIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => element.getClientRects().length > 0 && !element.closest('[inert]'),
  )
}

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
  /** A short sheet that explains one thing (a bill term): at most about 46 % of the screen. */
  short?: boolean
}

/**
 * Details open as a bottom sheet over the current screen, never as a new page. While it is the
 * top sheet, the keyboard stays inside it (#440): the rest of the page is inert, Tab and Shift+Tab
 * cycle through the sheet, Escape closes it, and the focus returns to the element that opened it.
 * Which sheet is on top is decided by `lib/sheetStack.ts` for all open sheets together (#516).
 */
export function BottomSheet({ title, onClose, children, short = false }: Props) {
  const { t } = useSettings()
  const titleId = useId()
  const root = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  // The latest onClose, so a caller's inline arrow does not re-run the open effect below (which
  // would release the background and move the focus to the opener and back on every render).
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  }, [onClose])

  // Runs once while the sheet is open: join the sheet stack (background, focus) and listen for Escape.
  useEffect(() => {
    const leave = root.current && panel.current ? openSheet(root.current, panel.current) : () => {}
    const onKey = (event: KeyboardEvent) => {
      // With sheets stacked (evidence over what-if over overview), one Escape closes only the top
      // one: the sheet that closes marks the event handled, and the others then ignore it.
      if (!escapeCloses(event, document.querySelectorAll('[role="dialog"]'), panel.current)) return
      event.preventDefault()
      close.current()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      leave()
    }
  }, [])

  const onPanelKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab' || !panel.current) return
    const target = trapTarget(focusableIn(panel.current), document.activeElement as HTMLElement | null, event.shiftKey, panel.current)
    if (target) {
      event.preventDefault()
      target.focus()
    }
  }

  return (
    <div ref={root} className="fixed inset-0 z-50 flex items-end justify-center">
      <button
        type="button"
        aria-label={t.close}
        tabIndex={-1}
        className="sheet-scrim absolute inset-0 bg-scrim"
        onClick={onClose}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onPanelKeyDown}
        className={`sheet-panel relative flex ${short ? 'max-h-[46dvh]' : 'max-h-[88dvh]'} w-full max-w-[480px] flex-col rounded-t-sheet bg-surface shadow-sheet outline-none`}
      >
        <div className="flex items-start gap-2 px-4 pt-2">
          <div className="flex-1 pt-3">
            <div aria-hidden="true" className="mx-auto -mt-2 mb-3 h-1 w-10 rounded-pill bg-line" />
            <h2 id={titleId} className="text-lg font-semibold text-ink">
              {title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="mt-1 inline-flex size-11 shrink-0 items-center justify-center rounded-pill text-ink hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="overflow-y-auto overscroll-contain px-4 pb-[calc(env(safe-area-inset-bottom)+24px)] pt-2">
          {children}
        </div>
      </div>
    </div>
  )
}
