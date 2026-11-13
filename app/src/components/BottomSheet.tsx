import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useSettings } from '../lib/settings.ts'

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
}

/** Details open as a bottom sheet over the current screen, never as a new page. */
export function BottomSheet({ title, onClose, children }: Props) {
  const { t } = useSettings()
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
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
