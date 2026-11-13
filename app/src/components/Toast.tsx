import type { Num } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { TokenText } from './cards.tsx'

interface Props {
  /** `message.text` of the label response; its `{{nN}}` tokens become number chips. */
  text: string
  numbers: Record<string, Num>
  /** Shown with the answer's message; it sends `basket: null`. */
  onUndo?: () => void
  onRetry?: () => void
  onClose: () => void
}

/**
 * The confirmation after a review answer, pinned above the bottom edge. It stays until the
 * customer closes it or undoes, so Undo never disappears on a timer. Screen readers hear
 * `text_rendered` through the overview's live region, not this visual copy.
 */
export function Toast({ text, numbers, onUndo, onRetry, onClose }: Props) {
  const { t } = useSettings()
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-[calc(env(safe-area-inset-bottom)+16px)]">
      <div className="toast-in pointer-events-auto flex w-full max-w-[448px] items-start gap-2 rounded-lg bg-ink py-2 pl-4 pr-1 text-surface shadow-float [&_:focus-visible]:outline-mint">
        <p className="flex-1 py-1.5 text-base leading-8">
          <TokenText text={text} numbers={numbers} />
        </p>
        {onUndo && (
          <button type="button" onClick={onUndo} className="min-h-11 shrink-0 px-2 text-base font-bold text-mint hover:underline">
            {t.undo}
          </button>
        )}
        {onRetry && (
          <button type="button" onClick={onRetry} className="min-h-11 shrink-0 px-2 text-base font-bold text-mint hover:underline">
            {t.retry}
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label={t.close}
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-pill text-on-deep-muted hover:text-surface"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  )
}
