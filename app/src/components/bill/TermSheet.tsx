import { useEffect, useId, useRef } from 'react'
import type { Num } from '../../api/types.ts'
import { useSettings } from '../../lib/settings.ts'
import { NumberChip } from '../NumberChip.tsx'

interface Props {
  /** The glossary entry's label and text, shown as received. */
  label: string
  text: string
  number?: Num
  onClose: () => void
}

/**
 * A short sheet (at most about 46% of the screen) that explains one bill term. Opened in place,
 * not through the URL; Escape, the scrim and "Close" close it, and focus returns to the term.
 */
export function TermSheet({ label, text, number, onClose }: Props) {
  const { t } = useSettings()
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  // The latest onClose, so the effect below runs only when the sheet opens and closes: a parent
  // re-render must not move focus back to the panel.
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  }, [onClose])

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const dialogs = document.querySelectorAll('[role="dialog"]')
      if (dialogs[dialogs.length - 1] === panel.current) close.current()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <button type="button" aria-label={t.close} tabIndex={-1} className="sheet-scrim absolute inset-0 bg-scrim" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="sheet-panel relative flex max-h-[46dvh] w-full max-w-[480px] flex-col gap-3 overflow-y-auto overscroll-contain rounded-t-sheet bg-surface px-4 pt-3 pb-[calc(env(safe-area-inset-bottom)+16px)] shadow-sheet outline-none"
      >
        <div aria-hidden="true" className="mx-auto h-1 w-10 shrink-0 rounded-pill bg-line" />
        <h2 id={titleId} className="text-lg font-semibold text-ink">
          {label}
        </h2>
        {number && (
          <div>
            <NumberChip number={number} />
          </div>
        )}
        <p className="text-base text-ink-2">{text}</p>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 w-full shrink-0 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
        >
          {t.close}
        </button>
      </div>
    </div>
  )
}
