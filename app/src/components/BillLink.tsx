import { billStrings } from '../lib/billStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { navigate } from '../lib/url.ts'

/**
 * Under the overview row of the opening (#332): opens `/bill` as a screen (a history entry, so
 * Back returns to the thread). `data-opening-part` keeps it apart from the question chips.
 */
export function BillLink() {
  const { lang } = useSettings()
  return (
    <button
      type="button"
      data-opening-part="bill-link"
      onClick={() => navigate('/bill')}
      className="inline-flex min-h-11 items-center gap-2 self-start rounded-md px-1 text-base font-semibold text-brand underline underline-offset-4 hover:text-deep"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M7 3h10v18l-2.5-1.5L12 21l-2.5-1.5L7 21z" strokeLinejoin="round" />
        <path d="M10 8h4M10 12h4" strokeLinecap="round" />
      </svg>
      {billStrings(lang).screenTitle}
    </button>
  )
}
