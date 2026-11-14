import type { BillsCard as BillsData, Card } from '../api/types.ts'
import { formatDate } from '../lib/i18n.ts'
import { useSettings } from '../lib/settings.ts'
import { useEstimateToggle } from '../lib/useEstimateToggle.ts'
import { ActionButton, CARD_TITLE, CardShell } from './cards.tsx'
import { EstimateBadge, EstimateNote } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'

/**
 * The bills card (contract section 3): the total due before payday, then one row per bill with
 * its status in the API's words, the amount due before payday and the next expected date.
 * Every amount is the API's `display`; the app never adds the rows up.
 */
export function BillsCard({ card }: { card: BillsData }) {
  const { lang, t } = useSettings()
  const estimate = useEstimateToggle()
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 pt-2">
          <h2 className={CARD_TITLE}>{card.title}</h2>
          {card.subtitle && <p className="text-sm text-muted">{card.subtitle}</p>}
        </div>
        {card.estimate && <EstimateBadge estimate={card.estimate} control={estimate.control} />}
      </div>
      {card.estimate && estimate.open && <EstimateNote estimate={card.estimate} id={estimate.id} />}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <NumberChip number={card.total} size="lg" />
        {/* The core may send the period as the subtitle too; say it once. */}
        {card.total.period.label !== card.subtitle && <span className="text-sm text-muted">{card.total.period.label}</span>}
      </div>

      <ul className="mt-3 flex flex-col divide-y divide-line">
        {card.items.map((item) => (
          // With large text the amount moves under the bill's lines instead of covering them (#541).
          <li key={item.bill_id} className="flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2">
            <div className="min-w-[min(6rem,100%)] flex-1 basis-0">
              <p className="text-base font-semibold text-ink">{item.label}</p>
              <p className="text-sm text-muted">{item.status_label}</p>
              {item.next_expected && <p className="text-sm text-muted">{t.billsNext(formatDate(item.next_expected, lang))}</p>}
            </div>
            <span className="ml-auto max-w-full shrink-0">
              <NumberChip number={item.due_until_payday} />
            </span>
          </li>
        ))}
      </ul>

      {card.items.length > 1 && <p className="mt-2 text-xs text-muted">{t.billsRounding}</p>}

      {card.actions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {card.actions.map((action, index) => (
            <ActionButton key={`${action.type}-${index}`} action={action} />
          ))}
        </div>
      )}
    </CardShell>
  )
}

/** Every `bills` card in a list of cards (the overview has at most one). */
export function BillsCards({ cards }: { cards: Card[] }) {
  return (
    <>
      {cards
        .filter((card): card is BillsData => card.type === 'bills' && 'items' in card && 'total' in card)
        .map((card) => (
          <BillsCard key={card.card_id} card={card} />
        ))}
    </>
  )
}
