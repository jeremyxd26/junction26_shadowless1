// The `peer` answer card (contract section 3): the customer against people like them.
import type { ReactNode } from 'react'
import type { Card, Num } from '../api/types.ts'
import { CardShell } from './cards.tsx'
import { NumberChip } from './NumberChip.tsx'

export type PeerData = Card & {
  type: 'peer'
  you: Num
  peer_median: Num
  peer_p25: Num
  peer_p75: Num
  percentile: Num
  vs_median: Num
  peer_group: { level: string; label: string; size: Num; comparable: boolean }
  note: string
}

function Row({ number, strong = false }: { number: Num; strong?: boolean }) {
  return (
    <li className="flex min-h-11 items-center justify-between gap-3 border-t border-line py-1">
      <span className={`min-w-0 text-sm ${strong ? 'font-semibold text-ink' : 'text-muted'}`}>{number.label}</span>
      <NumberChip number={number} size="inline" />
    </li>
  )
}

/**
 * The customer's monthly figure against the group's median, with the gap, the percentile, the
 * group's quarters and its size. Only group statistics; every number is the API's `display`.
 * Without a comparable group the card shows only its note; with no group at all the core sends no
 * card, and the reason is in the answer text.
 */
export function PeerCard({ card, header }: { card: PeerData; header: ReactNode }) {
  const group = card.peer_group
  return (
    <CardShell>
      {header}
      {group.comparable && (
        <>
          <div className="mt-3 flex flex-wrap items-end gap-x-3 gap-y-1">
            <div className="flex flex-col items-start gap-1">
              <span className="text-sm font-semibold text-ink">{card.you.label}</span>
              <NumberChip number={card.you} size="lg" />
            </div>
            <NumberChip number={card.vs_median} size="inline" tone="neutral" />
          </div>
          <ul className="mt-3 flex flex-col">
            <Row number={card.peer_median} strong />
            <Row number={card.percentile} />
            <Row number={card.peer_p25} />
            <Row number={card.peer_p75} />
          </ul>
          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            <span>{group.label}</span>
            <span aria-hidden="true">·</span>
            <span>{group.size.label}</span>
            <NumberChip number={group.size} size="inline" tone="neutral" />
          </p>
        </>
      )}
      <p className="mt-2 text-xs text-muted">{card.note}</p>
    </CardShell>
  )
}
