import type { EvidenceRow } from '../api/types.ts'

/** Calendar months a period touches: 1 Apr – 30 Sep is 6; within one month, 1 (#944). */
export function monthsBetween(start: string, end: string): number {
  const [sy, sm] = start.split('-').map(Number)
  const [ey, em] = end.split('-').map(Number)
  if (!sy || !sm || !ey || !em) return 0
  return Math.max(0, (ey - sy) * 12 + (em - sm) + 1)
}

/** The rows as they come (newest first), grouped by their month ("2026-09"), the groups in the same order. */
export function rowsByMonth(rows: EvidenceRow[]): { month: string; rows: EvidenceRow[] }[] {
  const groups: { month: string; rows: EvidenceRow[] }[] = []
  for (const row of rows) {
    const month = row.date.slice(0, 7)
    const last = groups[groups.length - 1]
    if (last && last.month === month) last.rows.push(row)
    else groups.push({ month, rows: [row] })
  }
  return groups
}
