import type { ReactNode } from 'react'
import { useSettings } from '../lib/settings.ts'

export function LoadingBlock({ lines = 3 }: { lines?: number }) {
  const { t } = useSettings()
  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-3">
      <span className="sr-only">{t.loading}</span>
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="h-6 animate-pulse rounded-md bg-sunken" style={{ width: `${90 - index * 12}%` }} />
      ))}
    </div>
  )
}

interface ErrorProps {
  message?: string
  onRetry?: () => void
  children?: ReactNode
}

export function ErrorBlock({ message, onRetry, children }: ErrorProps) {
  const { t } = useSettings()
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg bg-danger-tint p-4">
      <p className="text-base text-ink">{message ?? 'Something went wrong.'}</p>
      <div className="flex flex-wrap gap-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-pill bg-mint px-5 font-semibold text-ink hover:bg-mint-hover"
          >
            {t.retry}
          </button>
        )}
        {children}
      </div>
    </div>
  )
}
