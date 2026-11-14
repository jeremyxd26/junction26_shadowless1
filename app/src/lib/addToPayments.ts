// "Add to payments" (contract section 11.3): the app hands the action's payment draft to the host
// app as `sentti.paymentDraft`, exactly as the response carries it. Sentti never pays: the host
// shows the payment, the customer confirms it there, and the host executes it.
import type { AddToPaymentsAction, BillAction, BillHostScreenAction, PaymentDraft } from '../api/billTypes.ts'
import { handOver, hostScreenTarget, type HostScreenTarget } from './hostActions.ts'
import type { HostScope } from './hostBridge.ts'

export const PAYMENT_DRAFT_MESSAGE = 'paymentDraft' as const

/**
 * The draft as the host gets it: a copy with exactly the five fields of contract 11.3, values
 * unchanged (the `amount` Number object included). A field the API may add later never reaches
 * the host.
 */
export function hostDraft(draft: PaymentDraft): PaymentDraft {
  const { payee, iban, reference, amount, due_date } = draft
  return { payee, iban, reference, amount, due_date }
}

/**
 * Sends the draft's five fields to the host. Returns true when a host took it; otherwise the
 * hand-over helper fires the "continues in the bank app" notice.
 */
export function addToPayments(action: AddToPaymentsAction, scope?: HostScope): boolean {
  return handOver(PAYMENT_DRAFT_MESSAGE, hostDraft(action.draft), { scope })
}

/** The response's add-to-payments action, or null when it has none (a check failed). */
export function paymentAction(actions: { type: string }[]): AddToPaymentsAction | null {
  const action = actions.find((candidate) => candidate.type === 'add_to_payments')
  return action ? (action as AddToPaymentsAction) : null
}

/**
 * The response's `open_host_screen` actions whose target the app knows (since 0.3.3, `contact_bank`
 * after `add_to_payments`). A target the app does not know renders nothing, as everywhere else.
 */
export function hostScreenActions(
  actions: BillAction[],
  known: (target: unknown) => HostScreenTarget | null = hostScreenTarget,
): { label: string; target: HostScreenTarget }[] {
  return actions
    .filter((action): action is BillHostScreenAction => action.type === 'open_host_screen')
    .flatMap((action) => {
      const target = known(action.target)
      return target ? [{ label: action.label, target }] : []
    })
}
