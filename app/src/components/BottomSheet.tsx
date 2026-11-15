import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { FOCUSABLE, escapeCloses, trapTarget } from '../lib/focusTrap.ts'
import { useSheetDrag } from '../lib/sheetDrag.ts'
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
 * It can also be dragged down to close, by the grabber, the title row or content at its top (`lib/sheetDrag.ts`).
 */
export function BottomSheet({ title, onClose, children, short = false }: Props) {
  const { t } = useSettings()
  const titleId = useId()
  const root = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const scrim = useRef<HTMLButtonElement>(null)
  useSheetDrag(panel, scrim, onClose)
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
        ref={scrim}
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
        // A short sheet scrolls as a whole, title row included: with large text that row alone can take
        // most of 46dvh, and the text below needs the room (#680). A tall sheet keeps its title in place.
        className={`sheet-panel relative flex ${short ? 'max-h-[46dvh] overflow-y-auto overscroll-contain' : 'max-h-[88dvh]'} w-full max-w-[480px] flex-col rounded-t-sheet bg-surface shadow-sheet outline-none`}
      >
        {/* The grabber, centred on the sheet (Renat): 36 x 4 px in a 44 px tall strip that drags the sheet down;
            the close button sits at the strip's right end, so the title gets the whole row below. */}
        <div className="relative shrink-0">
          <div
            data-sheet-handle=""
            aria-hidden="true"
            className="flex h-11 cursor-grab select-none items-center justify-center active:cursor-grabbing"
          >
            <div className="h-1 w-9 rounded-pill bg-line-strong/40" />
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="absolute top-0 right-2 inline-flex size-11 items-center justify-center rounded-pill text-ink hover:bg-sunken"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <h2 id={titleId} data-sheet-handle="" className="shrink-0 px-4 text-lg font-semibold text-ink">
          {title}
        </h2>
        <div className={`${short ? '' : 'overflow-y-auto overscroll-contain '}px-4 pb-[calc(env(safe-area-inset-bottom)+24px)] pt-2`}>
          {children}
        </div>
      </div>
    </div>
  )
}
