import { useCallback } from 'react'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { EvidenceResponse } from '../api/types.ts'
import { formatDate, formatRowAmount } from '../lib/i18n.ts'
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
      {result.status === 'ready' && <EvidenceBody evidence={result.data} />}
    </BottomSheet>
  )
}

function EvidenceBody({ evidence }: { evidence: EvidenceResponse }) {
  const { lang, t } = useSettings()
  const { number } = evidence
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

      {evidence.rows.length > 0 && (
        <section aria-labelledby="ev-rows">
          <div className="flex items-baseline justify-between gap-2">
            <h3 id="ev-rows" className="text-sm font-semibold text-ink">
              {t.transactions}
            </h3>
            {evidence.row_count && (
              <span className="text-sm text-muted">
                {evidence.row_count.label}: {evidence.row_count.display}
              </span>
            )}
          </div>
          <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
            {evidence.rows.map((row) => (
              <li key={row.tx_id} className="flex min-h-14 items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-base text-ink">{row.merchant?.label ?? row.category}</p>
                  <p className="text-sm text-muted">
                    {formatDate(row.date, lang)}
                    {row.time ? ` · ${row.time}` : ''} · {row.category}
                  </p>
                </div>
                <span className="shrink-0 font-semibold tabular-nums text-ink">
                  {formatRowAmount(row.amount, row.currency, lang)}
                </span>
              </li>
            ))}
          </ul>
          {evidence.reconciles && <p className="mt-2 text-sm text-muted">{t.reconciles}</p>}
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
