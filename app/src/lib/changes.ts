// Where the numbers of a label response (`changes[]`, contract section 10.1) live on the overview.
// The app never recomputes them: each `after` Number replaces the overview Number with the same key.
import type { BreakdownCard, BreakdownItem, LabelChange, Num, OverviewResponse } from '../api/types.ts'

export const BASKET_STATES = ['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified']

/** The overview's basket breakdown: the breakdown card that lists the basket keys. */
export function isBasketsCard(card: OverviewResponse['cards'][number]): card is BreakdownCard {
  if (card.type !== 'breakdown' || !('items' in card)) return false
  return (card as BreakdownCard).items.some((item) => item.key === 'regular_essentials')
}

/** The new Number in the place of the old one; the overview's own label stays (it is shorter). */
function swap(current: Num, after: Num): Num {
  return { ...after, label: current.label }
}

/**
 * The overview with every changed number replaced by its `after` value:
 * `safe_to_spend` → hero, `irregular_reserve` → the hero's reserve, basket keys → basket rows,
 * `safe_to_save_monthly` / `safe_to_save` → the safe-to-save card. Keys it does not know are skipped.
 * A basket row that is not in the overview (the waiting row after an undo) is added with
 * `labels[key]` when its new amount is above zero.
 */
export function applyChanges(
  overview: OverviewResponse,
  changes: LabelChange[],
  labels: Record<string, string> = {},
): OverviewResponse {
  if (changes.length === 0) return overview
  const byKey = new Map(changes.map((change) => [change.key, change]))
  const next: OverviewResponse = { ...overview }

  const sts = byKey.get('safe_to_spend')
  const reserve = byKey.get('irregular_reserve')
  if (overview.hero && (sts || reserve)) {
    const hero = overview.hero
    const oldRef = hero.primary.evidence_ref
    const newRef = sts ? sts.after.evidence_ref : oldRef
    next.hero = {
      ...hero,
      primary: sts ? swap(hero.primary, sts.after) : hero.primary,
      evidence_ref: hero.evidence_ref === oldRef ? newRef : hero.evidence_ref,
      actions: hero.actions.map((action) =>
        action.type === 'open_evidence' && action.evidence_ref === oldRef && newRef
          ? { ...action, evidence_ref: newRef }
          : action,
      ),
      components: hero.components.map((component) =>
        reserve && component.key === 'irregular_reserve'
          ? { ...component, amount: swap(component.amount, reserve.after) }
          : component,
      ),
    }
  }

  const monthly = byKey.get('safe_to_save_monthly')
  const stock = byKey.get('safe_to_save')
  if (overview.safe_to_save && (monthly || stock)) {
    const card = overview.safe_to_save
    next.safe_to_save = {
      ...card,
      monthly: monthly ? swap(card.monthly, monthly.after) : card.monthly,
      stock: stock ? swap(card.stock, stock.after) : card.stock,
    }
  }

  if (BASKET_STATES.some((key) => byKey.has(key))) {
    next.cards = overview.cards.map((card) => {
      if (!isBasketsCard(card)) return card
      const items: BreakdownItem[] = card.items.map((item) => {
        const change = byKey.get(item.key)
        return change ? { ...item, amount: swap(item.amount, change.after) } : item
      })
      for (const key of BASKET_STATES) {
        const change = byKey.get(key)
        if (!change || items.some((item) => item.key === key) || change.after.value <= 0) continue
        const label = labels[key] ?? change.label
        items.push({ key, label, amount: { ...change.after, label }, share: null, change: null, flags: [] })
      }
      return { ...card, items }
    })
  }
  return next
}
