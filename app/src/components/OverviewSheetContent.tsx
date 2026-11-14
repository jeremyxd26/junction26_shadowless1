import { useId, type ReactNode } from 'react'
import type { OverviewResponse } from '../api/types.ts'
import { isBasketsCard } from '../lib/changes.ts'
import { useSettings } from '../lib/settings.ts'
import { openWhatIf } from '../lib/url.ts'
import { BasketStrip } from './BasketStrip.tsx'
import { BillsCards } from './BillsCard.tsx'
import { HeroCard, InsightCard } from './cards.tsx'
import { SafeToSaveCard } from './SafeToSaveCard.tsx'

/**
 * Everything that leaves the chat-first opening, for the overview sheet (#320; the sheet and its
 * triggers are #321): the full hero (reserve line and "How is this calculated?"), the baskets, the
 * bills, safe to save, the insights and the what-if entry, in that order.
 *
 * No review card and no motion live here. The baskets are a `BasketStrip` without `flight`, so no
 * element here has `id="baskets-title"` and the #35 flight never targets the sheet. `hero: null`
 * leaves the hero out with no placeholder.
 */
/** A compact section under the main answer: a 44 px row that opens its cards in place. */
function Section({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="group rounded-lg border border-line bg-surface">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 text-base font-semibold text-ink [&::-webkit-details-marker]:hidden">
        {title}
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
      </summary>
      <div className="flex flex-col gap-3 px-2 pb-3">{children}</div>
    </details>
  )
}

export function OverviewSheetContent({ overview }: { overview: OverviewResponse }) {
  const { t } = useSettings()
  const insightsId = useId()
  const baskets = overview.cards.find(isBasketsCard)
  return (
    <div className="flex flex-col gap-3">
      {/* One main answer on top, then compact sections (Renat's review). */}
      {overview.hero && <HeroCard card={overview.hero} />}
      {(baskets || overview.insights.length > 0) && (
        <Section title={t.overviewSections.money}>
          {baskets && <BasketStrip card={baskets} />}
          {overview.insights.length > 0 && (
            <section aria-labelledby={insightsId} className="flex flex-col gap-3">
              <h2 id={insightsId} className="text-base font-semibold text-ink">
                {t.insightsTitle}
              </h2>
              {overview.insights.map((insight) => (
                <InsightCard key={insight.insight_id} insight={insight} />
              ))}
            </section>
          )}
        </Section>
      )}
      <Section title={t.overviewSections.bills}>
        <BillsCards cards={overview.cards} />
      </Section>
      {overview.safe_to_save && (
        <Section title={t.overviewSections.save}>
          <SafeToSaveCard card={overview.safe_to_save} />
        </Section>
      )}

      {/* The what-if sheet with the contract's example request (Restaurants, 20%), as on the overview. */}
      <div>
        <button
          type="button"
          onClick={() => openWhatIf({ selection: { kind: 'category', value: 'Restaurants' }, cut_pct: 20 })}
          className="min-h-11 rounded-pill border-[1.5px] border-brand bg-surface px-4 py-2 text-left text-base font-medium text-brand hover:bg-mint-tint"
        >
          {t.whatIfEntry}
        </button>
      </div>
    </div>
  )
}
