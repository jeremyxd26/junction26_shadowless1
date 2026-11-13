import type { BreakdownCard, OverviewResponse } from '../api/types.ts'
import { BasketsCard, HeroCard, InsightCard, ReviewPlaceholder } from '../components/cards.tsx'
import { navigate } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'

function isBasketsCard(card: OverviewResponse['cards'][number]): card is BreakdownCard {
  if (card.type !== 'breakdown' || !('items' in card)) return false
  return (card as BreakdownCard).items.some((item) => item.key === 'regular_essentials')
}

/** The first screen: not an empty chat but this week's picture, then questions to ask. */
export function Overview({ overview }: { overview: OverviewResponse }) {
  const { t } = useSettings()
  const baskets = overview.cards.find(isBasketsCard)
  const review = overview.reviews[0]

  return (
    <div className="flex flex-col gap-4 pb-4">
      <p className="text-xl font-semibold text-ink">{overview.greeting}</p>
      <HeroCard card={overview.hero} />
      {review && <ReviewPlaceholder card={review} />}
      {baskets && <BasketsCard card={baskets} />}

      {overview.insights.length > 0 && (
        <section aria-labelledby="insights-title" className="flex flex-col gap-3">
          <h2 id="insights-title" className="text-base font-semibold text-ink">
            {t.insightsTitle}
          </h2>
          {overview.insights.map((insight) => (
            <InsightCard key={insight.insight_id} insight={insight} />
          ))}
        </section>
      )}

      {overview.suggested_questions.length > 0 && (
        <section aria-labelledby="ask-title" className="mt-2">
          <h2 id="ask-title" className="text-base font-semibold text-ink">
            {t.askTitle}
          </h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {overview.suggested_questions.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  onClick={() => navigate('/chat', { q: question })}
                  className="min-h-11 rounded-pill border border-mint-line bg-mint-tint px-4 py-2 text-left text-base font-medium text-ink hover:bg-mint"
                >
                  {question}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
