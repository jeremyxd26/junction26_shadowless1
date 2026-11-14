// "Add to payments" (#331, contract 11.3): shown only when the response carries the action, with
// the action's label. A tap hands the draft's five contract fields to the host app; in a plain browser the
// "continues in the bank app" notice shows (HostNotice, mounted by the page). `warnings` (today
// only a past due date) are a small note beside it, also when there is no button.
import type { BillExplainResponse } from '../../api/billTypes.ts'
import { addToPayments, paymentAction } from '../../lib/addToPayments.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { useSettings } from '../../lib/settings.ts'

export function AddToPayments({ response }: { response: Pick<BillExplainResponse, 'actions' | 'warnings'> }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const action = paymentAction(response.actions)
  if (!action && response.warnings.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {response.warnings.map((warning, index) => (
        <p key={index} className="text-sm text-ink-2">
          {warning}
        </p>
      ))}
      {action && (
        <>
          <button
            type="button"
            onClick={() => addToPayments(action)}
            className="inline-flex min-h-12 w-full items-center justify-center rounded-pill bg-mint px-5 text-base font-bold text-ink hover:bg-mint-hover"
          >
            {action.label}
          </button>
          <p className="text-sm text-muted">{s.paymentNote}</p>
        </>
      )}
    </div>
  )
}
