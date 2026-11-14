import { useSettings } from '../lib/settings.ts'
import { openOverview } from '../lib/url.ts'

/**
 * The last row of the opening (#321): it opens the overview sheet, like the header button (#322).
 * Disabled while a review answer is on its way. `data-opening-part` keeps it apart from the
 * question chips above it.
 */
export function OverviewRow({ disabled }: { disabled: boolean }) {
  const { t } = useSettings()
  return (
    <button
      type="button"
      data-opening-part="overview-row"
      onClick={openOverview}
      disabled={disabled}
      className="flex min-h-11 w-full items-center gap-3 rounded-lg border border-line bg-surface px-3 py-1 text-left hover:bg-sunken disabled:cursor-default disabled:opacity-40 disabled:hover:bg-surface"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6 shrink-0 text-brand" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
        <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
        <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
        <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
      </svg>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-base font-semibold leading-5 text-ink">{t.overview}</span>
        <span className="text-sm leading-4 text-muted">{t.overviewHint}</span>
      </span>
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}
