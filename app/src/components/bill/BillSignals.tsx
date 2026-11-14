// The warning signs of a bill (#331, contract section 11.2 `signals`): calm signs, never a verdict.
// Each signal's `text` is shown as received, then its `numbers` as chips in order; nothing inside
// the sentence is matched or replaced.
import type { BillSignal } from '../../api/billTypes.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { useSettings } from '../../lib/settings.ts'
import { NumberChip } from '../NumberChip.tsx'

export function BillSignals({ signals }: { signals: BillSignal[] }) {
  const { lang } = useSettings()
  if (signals.length === 0) return null
  const s = billStrings(lang)
  return (
    <section
      aria-label={s.warningSigns}
      className="flex gap-3 rounded-lg border-l-4 border-warning bg-warning-tint px-3 py-2.5"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="mt-0.5 size-6 shrink-0 text-warning" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 3.5 2.5 20h19L12 3.5Z" strokeLinejoin="round" />
        <path d="M12 10v4.5M12 17.25v.25" strokeLinecap="round" />
      </svg>
      <div className="min-w-0">
        <h3 className="text-sm font-bold text-warning">{s.warningSigns}</h3>
        <ul className="mt-0.5 flex flex-col gap-1.5">
          {signals.map((signal, index) => (
            <li key={`${signal.code}-${index}`} className="text-base text-ink-2">
              {signal.text}
              {signal.numbers.length > 0 && (
                <span className="ml-1.5 inline-flex flex-wrap gap-1.5 align-middle">
                  {signal.numbers.map((number, at) => (
                    <NumberChip key={`${number.evidence_ref ?? number.method}-${at}`} number={number} size="inline" tone="warning" />
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
