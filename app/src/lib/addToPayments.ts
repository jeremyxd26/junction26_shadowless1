// "Add to payments" (contract section 11.3): the app hands the action's payment draft to the host
// app as `sentti.paymentDraft`, exactly as the response carries it. Sentti never pays: the host
// shows the payment, the customer confirms it there, and the host executes it.
import type { AddToPaymentsAction } from '../api/billTypes.ts'
import { handOver } from './hostActions.ts'
import type { HostScope } from './hostBridge.ts'

export const PAYMENT_DRAFT_MESSAGE = 'paymentDraft' as const

/**
 * Sends the draft unchanged (the `amount` Number object included). Returns true when a host took
 * it; otherwise the hand-over helper fires the "continues in the bank app" notice.
 */
export function addToPayments(action: AddToPaymentsAction, scope?: HostScope): boolean {
  return handOver(PAYMENT_DRAFT_MESSAGE, action.draft, { scope })
}

/** The response's add-to-payments action, or null when it has none (a check failed). */
export function paymentAction(actions: { type: string }[]): AddToPaymentsAction | null {
  const action = actions.find((candidate) => candidate.type === 'add_to_payments')
  return action ? (action as AddToPaymentsAction) : null
}
