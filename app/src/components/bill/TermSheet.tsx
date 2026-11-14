import type { Num } from '../../api/types.ts'
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
 * it, the sheet stack and the one-sheet-per-Escape guard; like every sheet it closes by the X in its
 * title row, Escape or the scrim, and focus returns to the term.
 */
export function TermSheet({ label, text, number, onClose }: Props) {
  return (
    <BottomSheet title={label} onClose={onClose} short>
      <div className="flex flex-col gap-3">
        {number && (
          <div>
            <NumberChip number={number} />
          </div>
        )}
        <p className="text-base text-ink-2">{text}</p>
      </div>
    </BottomSheet>
  )
}
