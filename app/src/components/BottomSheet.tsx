import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { FOCUSABLE, escapeCloses, trapTarget } from '../lib/focusTrap.ts'
import { useSettings } from '../lib/settings.ts'

const SUPPORTS_INERT = typeof HTMLElement !== 'undefined' && 'inert' in HTMLElement.prototype

/**
 * Makes everything beside the sheet unreachable while it is open: `inert` on the siblings of the
 * sheet and of each of its ancestors up to `body` (the app, the toast, a sheet below this one,
 * anything portalled to `body`), or `aria-hidden` where `inert` is not supported. Returns the undo,
 * which touches only what this sheet changed, so stacked sheets restore each other in order.
 * A node marked `data-sheet-keep` stays live: the host notice, which shows above every sheet and
 * whose `role="status"` must still be announced and tappable.
 */
function hideBackground(sheet: HTMLElement): () => void {
  const changed: HTMLElement[] = []
  for (let keep: HTMLElement = sheet; keep.parentElement && keep !== document.body; keep = keep.parentElement) {
    for (const node of Array.from(keep.parentElement.children)) {
      if (node === keep || !(node instanceof HTMLElement) || node.hasAttribute('data-sheet-keep')) continue
      if (SUPPORTS_INERT ? node.inert : node.getAttribute('aria-hidden') === 'true') continue
      if (SUPPORTS_INERT) node.inert = true
      else node.setAttribute('aria-hidden', 'true')
      changed.push(node)
    }
  }
  return () => {
    for (const node of changed) {
      if (SUPPORTS_INERT) node.inert = false
      else node.removeAttribute('aria-hidden')
    }
  }
}

function focusableIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => element.getClientRects().length > 0 && !element.closest('[inert]'),
  )
}

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
}

/**
 * Details open as a bottom sheet over the current screen, never as a new page. While it is open,
 * the keyboard stays inside it (#440): the rest of the page is inert, Tab and Shift+Tab cycle
 * through the sheet, Escape closes it, and the focus returns to the element that opened it.
 */
export function BottomSheet({ title, onClose, children }: Props) {
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

  // Runs once while the sheet is open: hide the background, focus the panel, listen for Escape.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const showBackground = root.current ? hideBackground(root.current) : () => {}
    panel.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
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
      document.body.style.overflow = overflow
      // The background must be focusable again before the focus can go back to it.
      showBackground()
      previous?.focus?.()
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
        className="sheet-panel relative flex max-h-[88dvh] w-full max-w-[480px] flex-col rounded-t-sheet bg-surface shadow-sheet outline-none"
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
