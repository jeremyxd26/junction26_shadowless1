import { useEffect } from 'react'
import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { clientTurnRequest, clientTurns, openingChips, prefetchClientTurns } from './clientTurns.tsx'

/**
 * The opening's client-turn chips (#319), in `openingChips` order: each tap pushes its client turn
 * into the thread, without the API. `data-opening-part` keeps them apart from the question chips.
 */
export function OpeningChips() {
  // The client turns' code loads at idle once the opening shows, ahead of the first tap (#728).
  useEffect(() => prefetchClientTurns(), [])
  const { lang } = useSettings()
  const opening = useOpening()
  const shown = openingChips.filter((key) => clientTurns[key]?.visible())
  if (!opening || shown.length === 0) return null
  return (
    <ul data-opening-part="client-chips" className="flex flex-wrap gap-2">
      {shown.map((key) => {
        const request = clientTurnRequest(key, lang)
        return (
          <li key={key}>
            <button
              type="button"
              onClick={() => opening.pushClientTurn(request)}
              className="relative min-h-9 rounded-md border border-line bg-surface px-3 py-1.5 text-left text-[15px] leading-5 text-ink hover:bg-sunken after:absolute after:inset-x-0 after:-inset-y-1 after:content-['']"
            >
              {request.question}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
