import { useOpening } from '../lib/openingContext.ts'
import { useSettings } from '../lib/settings.ts'
import { clientTurns, openingChips } from './clientTurns.tsx'

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
    <ul data-opening-part="client-chips" className="flex flex-col items-start gap-2">
      {shown.map((key) => {
        const question = clientTurns[key].chip(lang)
        return (
          <li key={key}>
            <button
              type="button"
              onClick={() => opening.pushClientTurn({ question, render: key, id: key })}
              className="min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-medium text-ink hover:bg-mint"
            >
              {question}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
