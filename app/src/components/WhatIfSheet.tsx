import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api } from '../api/client.ts'
import { ApiError } from '../api/errors.ts'
import type { Estimate, Num, WhatIfResponse, WhatIfResult, WhatIfScenarioRequest } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { useEstimateToggle } from '../lib/useEstimateToggle.ts'
import { closeWhatIf, setParams } from '../lib/url.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { CARD_TITLE } from './cards.tsx'
import { EstimateBadge, EstimateNote } from './EstimateBadge.tsx'
import { NumberChip } from './NumberChip.tsx'
import { ErrorBlock, LoadingBlock } from './States.tsx'

interface Settled {
  key: string
  attempt: number
  result?: WhatIfResponse
  error?: unknown
  /** The last good result, kept on screen (dimmed) while a newer request runs. */
  shown: WhatIfResponse | null
}

/**
 * One what-if request per key. A newer key cancels the older request's update in the effect
 * cleanup, so a slow old answer can never replace a newer one (no out-of-order results).
 */
function useWhatIf(key: string, load: () => Promise<WhatIfResponse>) {
  const [attempt, setAttempt] = useState(0)
  const [settled, setSettled] = useState<Settled | null>(null)
  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    load().then(
      (result) => {
        if (!cancelled) setSettled({ key, attempt, result, shown: result })
      },
      (error: unknown) => {
        if (!cancelled) setSettled((previous) => ({ key, attempt, error, shown: previous?.shown ?? null }))
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, attempt, load])

  const current = settled !== null && settled.key === key && settled.attempt === attempt
  return {
    loading: !current,
    error: current ? settled.error : undefined,
    shown: settled?.shown ?? null,
    retry,
  }
}

function Row({ number, label }: { number: Num; label?: string }) {
  return (
    <li className="flex min-h-12 items-center justify-between gap-3 py-1.5">
      <span className="min-w-0 text-base text-ink-2">{label ?? number.label}</span>
      <span className="shrink-0">
        <NumberChip number={number} />
      </span>
    </li>
  )
}

/**
 * A what-if result exactly as the API returns it: every Number's `display` as is, the parts
 * as sent, the estimate badge, assumptions and caveats. Reusable for the `whatif` card in chat.
 */
export function WhatIfResultView({
  result,
  estimate,
  heading = true,
}: {
  result: WhatIfResult
  estimate: Estimate | null
  /** False where the scenario label is already the title (the sheet). */
  heading?: boolean
}) {
  const { t } = useSettings()
  const estimateToggle = useEstimateToggle()
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        {heading ? (
          <h3 className={`min-w-0 pt-2 ${CARD_TITLE}`}>{result.scenario.label}</h3>
        ) : (
          <p className="min-w-0 pt-3 text-sm text-muted">{result.saving_per_month.label}</p>
        )}
        {estimate && (
          <EstimateBadge
            estimate={estimate}
            control={estimateToggle.control}
          />
        )}
      </div>
      {estimate && estimateToggle.open && <EstimateNote estimate={estimate} id={estimateToggle.id} />}

      {result.status !== 'estimate' && result.caveats.length > 0 && (
        <div className="rounded-md bg-warning-tint p-3 text-base text-ink">
          {result.caveats.map((caveat) => (
            <p key={caveat}>{caveat}</p>
          ))}
        </div>
      )}

      <div>
        {heading && <p className="text-sm text-muted">{result.saving_per_month.label}</p>}
        <div className="mt-1">
          <NumberChip number={result.saving_per_month} size="lg" />
        </div>
      </div>

      <ul className="flex flex-col divide-y divide-line">
        <Row number={result.saving_per_week} />
        <Row number={result.saving_per_year} />
        <Row number={result.baseline_per_month} label={`${t.whatIfBaseline}: ${result.baseline_per_month.label}`} />
        <Row number={result.one_off_excluded} />
        <Row number={result.regular_excluded} />
      </ul>

      {result.assumptions.length > 0 && (
        <section className="text-sm text-ink-2">
          <h4 className="font-semibold text-ink">{t.whatIfAssumptions}</h4>
          <ul className="mt-1 list-disc pl-5">
            {result.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </section>
      )}
      {result.status === 'estimate' &&
        result.caveats.map((caveat) => (
          <p key={caveat} className="text-sm text-muted">
            {caveat}
          </p>
        ))}
    </div>
  )
}

/**
 * The what-if sheet (`?whatif=<kind>:<value>&cut=<pct>`). The slider moves freely; the API is
 * called on the input's native `change` event, which fires when a drag is released, on each
 * key step, and when VoiceOver or TalkBack sets the value (they send input + change, no pointer
 * or key events). A cancelled touch (for example a vertical swipe) and blur also commit.
 * About 0.5 s per call on the dev host.
 */
export function WhatIfSheet({ scenario }: { scenario: WhatIfScenarioRequest }) {
  const { lang, customerId, t } = useSettings()
  const sliderId = useId()
  const slider = useRef<HTMLInputElement>(null)
  const [cut, setCut] = useState(scenario.cut_pct)
  const { kind, value } = scenario.selection
  const committed = scenario.cut_pct
  // The last cut sent to the URL (and so to the API): change, pointercancel and blur can all
  // report the same value, and only the first of them may start a request.
  const lastSent = useRef(scenario.cut_pct)

  const load = useCallback(
    () => api.whatIf(customerId ?? '', { selection: { kind, value }, cut_pct: committed }, lang),
    [customerId, kind, value, committed, lang],
  )
  const { loading, error, shown, retry } = useWhatIf(`${customerId}|${kind}|${value}|${committed}|${lang}`, load)

  const commit = useCallback((next: number) => {
    if (!Number.isInteger(next) || next === lastSent.current) return
    lastSent.current = next
    setParams({ cut: String(next) })
  }, [])

  // React's onChange is the `input` event; the release is the native `change` event.
  useEffect(() => {
    const input = slider.current
    if (!input) return
    const onChange = () => commit(Number(input.value))
    input.addEventListener('change', onChange)
    return () => input.removeEventListener('change', onChange)
  }, [commit])

  return (
    <BottomSheet title={shown?.scenario.label ?? t.whatIfTitle} onClose={closeWhatIf}>
      <div className="flex flex-col gap-3">
        <div>
          <div className="flex items-baseline justify-between gap-3">
            <label htmlFor={sliderId} className="text-base font-semibold text-ink">
              {t.whatIfCut}
            </label>
            <output htmlFor={sliderId} className="text-base font-semibold tabular-nums text-ink">
              {t.whatIfCutValue(cut)}
            </output>
          </div>
          <input
            ref={slider}
            id={sliderId}
            type="range"
            min={1}
            max={100}
            step={1}
            value={cut}
            aria-valuetext={t.whatIfCutValue(cut)}
            onChange={(event) => setCut(Number(event.currentTarget.value))}
            onPointerCancel={(event) => commit(Number(event.currentTarget.value))}
            onBlur={(event) => commit(Number(event.currentTarget.value))}
            className="mt-2 h-11 w-full cursor-pointer accent-brand"
          />
          <p role="status" aria-live="polite" className="h-5 text-sm text-muted">
            {loading && shown ? t.whatIfUpdating : ''}
          </p>
        </div>

        {error !== undefined && !loading ? (
          <ErrorBlock
            message={error instanceof ApiError ? error.message : undefined}
            onRetry={error instanceof ApiError && !error.retryable ? undefined : retry}
          />
        ) : shown ? (
          <div aria-busy={loading} className={loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
            <WhatIfResultView result={shown} estimate={shown.estimate} heading={false} />
          </div>
        ) : (
          <LoadingBlock lines={5} />
        )}
      </div>
    </BottomSheet>
  )
}
