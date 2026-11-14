// `/bill` (#332): the bill flow as its own screen, in live and mock builds. Sample gallery →
// reading → fields → explanation → Add to payments. Back (the header's chevron, or "Done") returns
// to the thread; `/bill` is never the first screen, so Back here never sends `sentti.close`.
import { BillFlow } from '../components/bill/BillFlow.tsx'
import { billStrings } from '../lib/billStrings.ts'
import { useSettings } from '../lib/settings.ts'
import { goBack } from '../lib/url.ts'

export default function BillScreen() {
  const { lang } = useSettings()
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-card-title font-bold text-brand">{billStrings(lang).screenTitle}</h1>
      <BillFlow onDone={goBack} />
    </div>
  )
}
