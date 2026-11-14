import { useSettings } from '../lib/settings.ts'
import { useCountdown } from '../lib/useCountdown.ts'

interface Props {
  onRetry: () => void
  /** The time (`Date.now()`) the server's `Retry-After` allows the next try; null when it gave none. */
  until: number | null
  className: string
}

/** "Try again", held back with a countdown while the server asked to wait (`Retry-After`, for example on 429). */
export function RetryButton({ onRetry, until, className }: Props) {
  const { t } = useSettings()
  const seconds = useCountdown(until)
  return (
    <button type="button" onClick={onRetry} disabled={seconds > 0} className={`${className} disabled:cursor-wait disabled:opacity-80`}>
      {seconds > 0 ? t.retryIn(seconds) : t.retry}
    </button>
  )
}
