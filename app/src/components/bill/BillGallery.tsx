import { useCallback } from 'react'
import { billApi } from '../../api/bill.ts'
import type { BillSample, BillSamplesResponse } from '../../api/billTypes.ts'
import type { Language } from '../../api/types.ts'
import { ApiError } from '../../api/errors.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { useSettings } from '../../lib/settings.ts'
import { useLoad } from '../../lib/useLoad.ts'
import { ErrorBlock, LoadingBlock } from '../States.tsx'

interface Props {
  onPick: (sampleId: string) => void
}

/**
 * The sample bills per language, kept for the session once loaded (#332): when the thread comes
 * back from /cards, a bill turn shows its gallery at full height at once, so the browser restores
 * the page to the same place instead of a shorter one.
 */
const loadedSamples = new Map<Language, BillSamplesResponse>()

/** The sample bills (contract 11.4, `GET /api/bill/samples`) as a two-column grid of tiles. */
export function BillGallery({ onPick }: Props) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const kept = loadedSamples.get(lang)
  const load = useCallback(
    () =>
      billApi.samples(lang).then((data) => {
        loadedSamples.set(lang, data)
        return data
      }),
    [lang],
  )
  const loaded = useLoad(kept ? null : `bill-samples|${lang}`, load)
  const result: typeof loaded = kept ? { status: 'ready', data: kept, refresh: () => {} } : loaded

  return (
    <section aria-labelledby="bill-gallery-title" className="flex flex-col gap-3">
      <div>
        <h2 id="bill-gallery-title" data-step-heading tabIndex={-1} className="text-card-title font-bold text-brand">
          {s.galleryTitle}
        </h2>
        <p className="mt-0.5 text-sm text-muted">{s.galleryHint}</p>
      </div>
      {result.status === 'loading' && <LoadingBlock lines={3} />}
      {result.status === 'error' && (
        <ErrorBlock
          message={result.error instanceof ApiError ? result.error.message : undefined}
          onRetry={result.error instanceof ApiError && !result.error.retryable ? undefined : result.retry}
        />
      )}
      {result.status === 'ready' && (
        <ul className="grid grid-cols-2 gap-3">
          {result.data.samples.map((sample) => (
            <li key={sample.sample_id}>
              <SampleTile sample={sample} onPick={onPick} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function SampleTile({ sample, onPick }: { sample: BillSample; onPick: (sampleId: string) => void }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  return (
    <button
      type="button"
      onClick={() => onPick(sample.sample_id)}
      className="@container flex min-h-11 w-full flex-col overflow-hidden rounded-lg border border-line bg-surface text-left transition-colors duration-(--duration-fast) hover:border-brand active:bg-mint-tint"
    >
      <span className="block bg-sunken p-3">
        <img src={sample.image_url} alt="" className="mx-auto aspect-[4/5] w-full max-w-36 rounded-sm shadow-sm" />
      </span>
      {/* With large text the tile is narrow in rem (under 7rem; at normal size it is 8.6–9.4rem), and
          only then the words hyphenate in the UI language, so normal-size line breaks stay as they
          were. A word that still does not fit breaks as a last resort instead of being clipped (#541). */}
      <span lang={lang} className="flex min-w-0 flex-col gap-0.5 px-3 py-2 break-words @max-[7rem]:hyphens-auto">
        <span className="text-base font-semibold text-ink">{sample.title}</span>
        <span className="text-xs text-muted">{s.sampleLanguage[sample.language] ?? sample.language}</span>
      </span>
    </button>
  )
}
