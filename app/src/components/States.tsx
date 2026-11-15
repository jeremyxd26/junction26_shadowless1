import type { ReactNode } from 'react'
import { useSettings } from '../lib/settings.ts'
import { RetryButton } from './RetryButton.tsx'

/**
 * Skeleton lines while something loads. It says "Loading…" in its own live region, unless
 * `announce` is false because the place around it already announces the wait (a client turn's step).
 */
export function LoadingBlock({ lines = 3, announce = true }: { lines?: number; announce?: boolean }) {
  const { t } = useSettings()
  return (
    <div role={announce ? 'status' : undefined} aria-live={announce ? 'polite' : undefined} className="flex flex-col gap-3">
      {announce && <span className="sr-only">{t.loading}</span>}
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="h-6 shimmer rounded-md" style={{ width: `${90 - index * 12}%` }} />
      ))}
    </div>
  )
}

interface ErrorProps {
  message?: string
  onRetry?: () => void
  /** The time (`Date.now()`) the server's `Retry-After` allows the next try; Try again waits until then. */
  until?: number | null
  children?: ReactNode
}

export function ErrorBlock({ message, onRetry, until = null, children }: ErrorProps) {
  const { t } = useSettings()
  return (
    // Only the message is the alert; Try again (with its countdown after a 429) sits outside it, so a
    // screen reader does not announce every second of the countdown.
    <div className="flex flex-col items-start gap-3 rounded-lg bg-danger-tint p-4">
      <p role="alert" className="text-base text-ink">
        {message ?? t.errorGeneric}
      </p>
      <div className="flex flex-wrap gap-2">
        {onRetry && (
          <RetryButton
            onRetry={onRetry}
            until={until}
            className="min-h-11 rounded-3xl bg-mint px-5 py-2 font-semibold text-ink hover:bg-mint-hover"
          />
        )}
        {children}
      </div>
    </div>
  )
}
