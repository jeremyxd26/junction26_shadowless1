import type { OverviewResponse } from '../api/types.ts'
import { useSettings } from '../lib/settings.ts'
import { closeOverview } from '../lib/url.ts'
import { BottomSheet } from './BottomSheet.tsx'
import { OverviewSheetContent } from './OverviewSheetContent.tsx'

/**
 * The overview as a bottom sheet over the thread (#321): `?overview=1`, opened by the header button
 * (#322) or the overview row, closed by Back. Evidence and what-if sheets opened from it stack above.
 */
export function OverviewSheet({ overview }: { overview: OverviewResponse }) {
  const { t } = useSettings()
  return (
    <BottomSheet title={t.overview} onClose={closeOverview}>
      <OverviewSheetContent overview={overview} />
    </BottomSheet>
  )
}
