import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { clientTurnRequest, clientTurns, openingChips } from './clientTurns.tsx'

/**
 * The opening's client-turn chips (#319), in `openingChips` order: each tap pushes its client turn
 * into the thread, without the API. `data-opening-part` keeps them apart from the question chips.
 */
export function OpeningChips() {
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
              className="min-h-11 rounded-pill border border-mint-line bg-mint-tint px-3 py-1.5 text-left text-[15px] font-medium leading-5 text-ink hover:bg-mint"
            >
              {request.question}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
