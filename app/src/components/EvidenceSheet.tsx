import { useCallback, useState } from 'react'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { EvidenceResponse, EvidenceRow } from '../api/types.ts'
import { formatDate } from '../lib/i18n.ts'
import { useLoad } from '../lib/useLoad.ts'
import { closeEvidence } from '../lib/url.ts'
import { useSettings } from '../lib/settings.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { NumberChip } from './NumberChip.tsx'
import { ErrorBlock, LoadingBlock } from './States.tsx'

/** The evidence for one number, opened with `?evidence=<ref>` over the current screen. */
export function EvidenceSheet({ evidenceRef }: { evidenceRef: string }) {
  const { lang, customerId, t } = useSettings()
  const load = useCallback(() => api.evidence(evidenceRef, customerId ?? '', lang), [evidenceRef, customerId, lang])
  const result = useLoad(customerId ? `${evidenceRef}|${customerId}|${lang}` : null, load)

  const title = result.status === 'ready' ? result.data.title : t.howCalculated
  return (
    <BottomSheet title={title} onClose={closeEvidence}>
      {result.status === 'loading' && <LoadingBlock lines={4} />}
      {result.status === 'error' && (
        <ErrorBlock
          message={result.error instanceof ApiError ? result.error.message : undefined}
          onRetry={result.error instanceof ApiError && !result.error.retryable ? undefined : result.retry}
        />
      )}
      {result.status === 'ready' && (
        // Keyed, so the extra pages of one evidence never leak into the next one.
        <EvidenceBody key={`${evidenceRef}|${customerId}|${lang}`} evidence={result.data} />
      )}
    </BottomSheet>
  )
}

interface Pages {
  rows: EvidenceRow[]
  cursor: string | null
  loading: boolean
  error: string | null
}

function EvidenceBody({ evidence }: { evidence: EvidenceResponse }) {
  const { lang, customerId, t } = useSettings()
  const { number } = evidence
  const [pages, setPages] = useState<Pages>({ rows: evidence.rows, cursor: evidence.next_cursor, loading: false, error: null })

  const showMore = async () => {
    if (!pages.cursor || pages.loading) return
    setPages((current) => ({ ...current, loading: true, error: null }))
    try {
      const next = await api.evidence(evidence.evidence_ref, customerId ?? '', lang, pages.cursor)
      setPages((current) => {
        const seen = new Set(current.rows.map((row) => row.tx_id))
        const fresh = next.rows.filter((row) => !seen.has(row.tx_id))
        return { rows: [...current.rows, ...fresh], cursor: next.next_cursor, loading: false, error: null }
      })
    } catch (error) {
      setPages((current) => ({
        ...current,
        loading: false,
        error: error instanceof ApiError ? error.message : t.errorGeneric,
      }))
    }
  }

  // "Add up" is only true of the full list: every page loaded and the API says it reconciles.
  const allRows = pages.cursor === null && (evidence.row_count === null || pages.rows.length >= evidence.row_count.value)
  const showReconciles = evidence.reconciles === true && allRows
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <NumberChip number={{ ...number, evidence_ref: null }} />
        <span className="text-sm text-muted">{number.period.label}</span>
      </div>

      <section aria-labelledby="ev-how">
        <h3 id="ev-how" className="text-sm font-semibold text-ink">
          {t.howCalculated}
        </h3>
        <p className="mt-1 text-base text-ink-2">{evidence.method.summary}</p>
      </section>

      {pages.rows.length > 0 && (
        <section aria-labelledby="ev-rows">
          <div className="flex items-baseline justify-between gap-2">
            <h3 id="ev-rows" className="text-sm font-semibold text-ink">
              {t.transactions}
            </h3>
            {evidence.row_count && (
              <span className="text-sm text-muted">
                {evidence.row_count.label} <NumberChip number={evidence.row_count} size="inline" tone="neutral" />
              </span>
            )}
          </div>
          <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
            {pages.rows.map((row) => (
              <li key={row.tx_id} className="flex min-h-14 items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-base text-ink">{row.merchant?.label ?? row.category}</p>
                  <p className="text-sm text-muted">
                    {formatDate(row.date, lang)}
                    {row.time ? ` · ${row.time}` : ''} · {row.category}
                  </p>
                </div>
                <span className="shrink-0 font-semibold tabular-nums text-ink">
                  {row.display}
                </span>
              </li>
            ))}
          </ul>
          {pages.cursor && (
            <button
              type="button"
              onClick={showMore}
              disabled={pages.loading}
              aria-busy={pages.loading}
              className="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint disabled:cursor-wait disabled:opacity-70"
            >
              {pages.loading ? t.loading : t.showMore}
            </button>
          )}
          {pages.error && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {pages.error}
            </p>
          )}
          {showReconciles && <p className="mt-2 text-sm text-muted">{t.reconciles}</p>}
        </section>
      )}

      {evidence.parts.length > 0 && (
        <section aria-labelledby="ev-parts">
          <h3 id="ev-parts" className="text-sm font-semibold text-ink">
            {t.madeOf}
          </h3>
          <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
            {evidence.parts.map((part) => (
              <li key={`${part.role}-${part.number.evidence_ref}`} className="flex min-h-14 items-center justify-between gap-3 px-3 py-1.5">
                <span className="min-w-0 text-base text-ink">{part.number.label}</span>
                <NumberChip number={part.number} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-col gap-1 border-t border-line pt-3 text-sm text-muted">
        <p>
          {t.method}: <span className="font-mono text-xs break-all">{evidence.method.id}</span>
        </p>
        <p>{evidence.privacy_note}</p>
      </div>
    </div>
  )
}
