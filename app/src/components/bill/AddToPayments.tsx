// The bill's actions (#331, contract 11.2-11.3), each shown only when the response carries it,
// picked by `type`, never by index:
// - "Add to payments": a tap hands the draft's five contract fields to the host app; in a plain
//   browser the "continues in the bank app" notice shows (HostNotice, mounted by the page);
// - `open_host_screen` (since 0.3.3, `contact_bank`): the way to a human at the bank, through the
//   same path as every other host-screen chip; a target the app does not know renders nothing.
// `warnings` (today only a past due date) are a small note beside them, also without a button.
import type { BillExplainResponse } from '../../api/billTypes.ts'
import { addToPayments, hostScreenActions, paymentAction } from '../../lib/addToPayments.ts'
import { billStrings } from '../../lib/billStrings.ts'
import { openHostScreen } from '../../lib/hostActions.ts'
import { useSettings } from '../../lib/settings.ts'

/** The look of an action chip in an answer (AnswerView's ACTION_CHIP). */
const ACTION_CHIP =
  'inline-flex min-h-11 items-center justify-center rounded-pill border-[1.5px] border-brand bg-surface px-4 text-left text-base font-semibold text-brand hover:bg-mint-tint'

export function AddToPayments({ response }: { response: Pick<BillExplainResponse, 'actions' | 'warnings'> }) {
  const { lang } = useSettings()
  const s = billStrings(lang)
  const action = paymentAction(response.actions)
  const screens = hostScreenActions(response.actions)
  if (!action && screens.length === 0 && response.warnings.length === 0) return null
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
      {screens.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {screens.map((screen) => (
            <button key={screen.target} type="button" className={ACTION_CHIP} onClick={() => openHostScreen(screen.target)}>
              {screen.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
