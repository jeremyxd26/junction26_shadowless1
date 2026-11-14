// What a card shows inside a chat answer (#684): one answer, read once. The question is in the
// bubble and the sentence is above the card, so the card drops its title (it restates the
// question) and its own explanation texts, and shows the period once, one main number and at most
// three "label — value" rows. Which fields go where is decided by card type, never by comparing
// texts: a live answer paraphrases its card, so a text match would miss the repeats on the demo.
import type { BreakdownCard, Card, Comparison, MetricCard, Num, SafeToSaveCard } from '../api/types.ts'

export const MAX_ROWS = 3

export interface FigureRow {
  key: string
  label: string
  number: Num
  /** A change ("▲ €367.40 more"), coloured only by the response's own `comparison.tone`. */
  tone?: Comparison['tone']
}

export interface AnswerFigures {
  /** The period, once: the main number's `period.label`. */
  caption: string | null
  /** A name in normal weight that is the answer's result (the spender profile), never the card title. */
  title: string | null
  /** Short labels under the title (the profile's traits), without their notes. */
  tags: string[]
  main: Num | null
  rows: FigureRow[]
  /** The card's only content when it has no figures (a peer group that is not comparable). */
  note: string | null
}

type ProfileCard = Card & {
  profile: { key: string; label: string; description: string }
  traits: { key: string; label: string; note: string }[]
  features: { key: string; decides_label: boolean; value: Num }[]
}

type PeerCard = Card & {
  you: Num
  peer_median: Num
  percentile: Num
  vs_median: Num
  peer_group: { comparable: boolean }
  note: string
}

type WhatIfCard = Card & {
  result: { status?: string; saving_per_month: Num; saving_per_week: Num; saving_per_year: Num; baseline_per_month: Num }
}

const row = (number: Num | null | undefined, key: string): FigureRow[] =>
  number ? [{ key, label: number.label, number }] : []

const comparisonRow = (comparison: Comparison | null | undefined): FigureRow[] =>
  comparison ? [{ key: 'comparison', label: comparison.label, number: comparison.change, tone: comparison.tone }] : []

function figures(main: Num | null, rows: FigureRow[], extra: Partial<AnswerFigures> = {}): AnswerFigures {
  return {
    caption: main?.period.label ?? null,
    title: null,
    tags: [],
    main,
    rows: rows.slice(0, MAX_ROWS),
    note: null,
    ...extra,
  }
}

/**
 * A later card of the same answer (the peer card after the profile): one main number per answer,
 * so its main number becomes its first row, still at most three rows; and its caption goes when
 * the card before it showed the same period.
 */
export function asLaterCard(figures: AnswerFigures, previousCaption: string | null): AnswerFigures {
  const rows = figures.main ? [{ key: 'main', label: figures.main.label, number: figures.main }, ...figures.rows] : figures.rows
  return {
    ...figures,
    caption: figures.caption === previousCaption ? null : figures.caption,
    main: null,
    rows: rows.slice(0, MAX_ROWS),
  }
}

/** The caption a card shows, or null; never throws (a malformed card falls back in its own boundary). */
export function captionOf(card: Card): string | null {
  try {
    return answerFigures(card)?.caption ?? null
  } catch {
    return null
  }
}

/** The baskets breakdown keeps its own card (the overview's basket rows). */
export function isBasketsBreakdown(card: BreakdownCard): boolean {
  return card.items.some((item) => item.key === 'regular_essentials')
}

/**
 * The figures of a card in a chat answer, or null for a type that keeps its own renderer (bills,
 * review, the baskets breakdown, and any type the app does not know).
 */
export function answerFigures(card: Card): AnswerFigures | null {
  switch (card.type) {
    case 'metric': {
      const metric = card as MetricCard
      return figures(metric.primary, [
        ...comparisonRow(metric.comparison),
        ...(metric.secondary ?? []).map((number, index) => ({ key: number.id ?? `secondary-${index}`, label: number.label, number })),
      ])
    }
    case 'breakdown': {
      const breakdown = card as BreakdownCard
      if (isBasketsBreakdown(breakdown)) return null
      return figures(breakdown.total, [
        ...comparisonRow(breakdown.comparison),
        ...breakdown.items.map((item) => ({ key: item.key, label: item.label, number: item.amount })),
      ])
    }
    case 'safe_to_save': {
      const save = card as SafeToSaveCard
      // When the month is 0 the core sends a reason whose text has no digits: its amount comes first.
      const reason: FigureRow[] = save.reason
        ? [{ key: 'reason', label: save.reason.category?.label ?? save.reason.amount.label, number: save.reason.amount }]
        : []
      return figures(save.monthly, [...reason, ...row(save.weekly, 'weekly'), ...row(save.daily, 'daily'), ...row(save.stock, 'stock')])
    }
    case 'whatif': {
      const result = (card as WhatIfCard).result
      // Not offered (nothing to cut): no "€0.00 a month" headline; the frame with its title, as before.
      if (!result?.saving_per_month || result.status === 'not_offered') return null
      return figures(result.saving_per_month, [
        ...row(result.saving_per_week, 'week'),
        ...row(result.saving_per_year, 'year'),
        ...row(result.baseline_per_month, 'baseline'),
      ])
    }
    case 'profile': {
      const profile = card as ProfileCard
      // The feature that decides the profile is the main number; then the API's order.
      const features = [...profile.features].sort((a, b) => Number(b.decides_label) - Number(a.decides_label))
      const [first, ...rest] = features
      return figures(
        first?.value ?? null,
        rest.map((feature) => ({ key: feature.key, label: feature.value.label, number: feature.value })),
        { title: profile.profile.label, tags: profile.traits.map((trait) => trait.label) },
      )
    }
    case 'peer': {
      // The peer title names what is compared ("Restaurants: you and people like you"), not the
      // question, so it stays, in the normal weight.
      const peer = card as PeerCard
      if (!peer.peer_group.comparable) return { ...figures(null, []), title: peer.title, note: peer.note }
      return figures(
        peer.you,
        [...row(peer.peer_median, 'median'), ...row(peer.vs_median, 'vs_median'), ...row(peer.percentile, 'percentile')],
        { title: peer.title },
      )
    }
    default:
      return null
  }
}
