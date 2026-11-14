import type { Num } from '../../api/types.ts'
import { useSettings } from '../../lib/settings.ts'
import { BottomSheet } from '../BottomSheet.tsx'
import { NumberChip } from '../NumberChip.tsx'

interface Props {
  /** The glossary entry's label and text, shown as received. */
  label: string
  text: string
  number?: Num
  onClose: () => void
}

/**
 * A short sheet (at most about 46% of the screen) that explains one bill term. Opened in place,
 * not through the URL. It is a `BottomSheet` (#582), so it has the Tab trap, the inert page behind
 * it, the sheet stack and the one-sheet-per-Escape guard; Escape, the scrim, the X and "Close" close
 * it, and focus returns to the term.
 */
export function TermSheet({ label, text, number, onClose }: Props) {
  const { t } = useSettings()
  return (
    <BottomSheet title={label} onClose={onClose} short>
      <div className="flex flex-col gap-3">
        {number && (
          <div>
            <NumberChip number={number} />
          </div>
        )}
        <p className="text-base text-ink-2">{text}</p>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 w-full shrink-0 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-base font-semibold text-brand hover:bg-mint-tint"
        >
          {t.close}
        </button>
      </div>
    </BottomSheet>
  )
}
