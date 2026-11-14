import { useLayoutEffect, useRef } from 'react'
import type { Num } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { TokenText } from './cards.tsx'
import { RetryButton } from './RetryButton.tsx'

interface Props {
  /** `message.text` of the label response; its `{{nN}}` tokens become number chips. */
  text: string
  numbers: Record<string, Num>
  /** Shown with the answer's message; it sends `basket: null`. */
  onUndo?: () => void
  onRetry?: () => void
  /** With `onRetry`: the `Retry-After` time before which Retry waits. */
  retryUntil?: number | null
  onClose: () => void
}

/**
 * The confirmation after a review answer, pinned 8 px above the composer, so the input is never
 * covered. The composer's height is measured (the form around `#chat-input`, which already holds the
 * safe area in its padding) and followed as it changes, for example with 200 % text. The answer's
 * toast closes by itself after 6 s (Undo stays on the answered card), and when the customer closes
 * it or asks the next question; a toast with Retry stays until it is closed. Screen readers hear
 * `text_rendered` through the overview's live region, not this copy.
 */
export function Toast({ text, numbers, onUndo, onRetry, retryUntil = null, onClose }: Props) {
  const { t } = useSettings()
  const box = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const node = box.current
    const composer = document.getElementById('chat-input')?.closest('form')
    if (!node || !composer) return
    const place = () => {
      node.style.bottom = `${composer.getBoundingClientRect().height + 8}px`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(composer)
    return () => observer.disconnect()
  }, [])
  return (
    // Without a composer on the page, it sits 16 px above the safe area.
    <div
      ref={box}
      className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+16px)] z-40 flex justify-center px-4"
    >
      <div className="toast-in pointer-events-auto flex w-full max-w-[448px] items-start gap-1 rounded-lg bg-ink py-2 pl-4 pr-1 text-surface shadow-float [&_:focus-visible]:outline-mint">
        <p className="flex-1 py-2 text-sm leading-6">
          <TokenText text={text} numbers={numbers} />
        </p>
        {/* Actions in one narrow column, so the message keeps most of the width. */}
        <div className="flex shrink-0 flex-col items-end">
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="inline-flex size-11 items-center justify-center rounded-pill text-on-deep-muted hover:text-surface"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
          {onUndo && (
            <button type="button" onClick={onUndo} className="min-h-11 px-3 text-base font-bold text-mint hover:underline">
              {t.undo}
            </button>
          )}
          {onRetry && (
            <RetryButton
              onRetry={onRetry}
              until={retryUntil}
              className="min-h-11 max-w-36 px-3 text-right text-base font-bold text-mint hover:underline"
            />
          )}
        </div>
      </div>
    </div>
  )
}
