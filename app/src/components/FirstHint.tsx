import { useState } from 'react'
import { dismissFirstHint, firstHintDismissed } from '../lib/firstHint.ts'
import { useSettings } from '../lib/settings.ts'

/**
 * A short visible hint for the header icons and the composer's paperclip, shown once (Renat's
 * review): their accessible names already exist, this says what they do in words.
 */
export function FirstHint({ show }: { show: boolean }) {
  const { t } = useSettings()
  const [, rerender] = useState(0)
  if (!show || firstHintDismissed()) return null
  return (
    <div role="note" className="card-enter mb-3 flex items-start gap-3 rounded-lg border border-line bg-mint-tint px-3 py-2">
      <p className="flex-1 text-sm text-ink">{t.firstHint}</p>
      <button
        type="button"
        onClick={() => {
          dismissFirstHint()
          rerender((n) => n + 1)
        }}
        className="min-h-11 shrink-0 px-1 text-sm font-semibold text-brand underline underline-offset-4"
      >
        {t.gotIt}
      </button>
    </div>
  )
}
