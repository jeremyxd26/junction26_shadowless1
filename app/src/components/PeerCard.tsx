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
    // With large text the chip moves under the label instead of running past the card (#541).
    <li className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line py-1">
      <span className={`min-w-[min(5rem,100%)] flex-1 basis-0 text-sm ${strong ? 'font-semibold text-ink' : 'text-muted'}`}>
        {number.label}
      </span>
      <span className="ml-auto max-w-full shrink-0">
        <NumberChip number={number} size="inline" wrap />
      </span>
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
            <div className="flex max-w-full flex-col items-start gap-1">
              <span className="text-sm font-semibold text-ink">{card.you.label}</span>
              {/* The large chip needs about 265 px for "€1,180.21 a month"; below 360 px the medium one fits. */}
              <span className="hidden min-[360px]:inline-flex">
                <NumberChip number={card.you} size="lg" />
              </span>
              <span className="inline-flex min-[360px]:hidden">
                <NumberChip number={card.you} />
              </span>
            </div>
            <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
              <span className="text-sm text-muted">{card.vs_median.label}</span>
              <NumberChip number={card.vs_median} size="inline" tone="neutral" />
            </span>
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
