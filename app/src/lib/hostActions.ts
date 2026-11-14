// Hands an action over to the host app (contract §11.3: `sentti.paymentDraft`,
// `sentti.openHostScreen`, …). Inside a host the message goes through `sendToHost`; in a plain
// browser, or when the host's handler throws, nothing is sent and `HostNotice` tells the customer
// that this step continues in the bank app.
import { sendToHost, type HostScope } from './hostBridge.ts'

/** The window event `HostNotice` listens to; fired when no host took a hand-over. */
export const HANDOVER_EVENT = 'sentti:handover'

export interface HandOverDetail {
  /** The message name without the `sentti.` prefix, e.g. `paymentDraft`. */
  name: string
}

/**
 * Sends `sentti.<name>` with `payload` to the host. Returns true when the host took it; otherwise
 * returns false and fires `HANDOVER_EVENT`, so the notice can show.
 */
export function handOver(name: string, payload: Record<string, unknown> = {}, scope?: HostScope): boolean {
  if (sendToHost(name, payload, scope)) return true
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<HandOverDetail>(HANDOVER_EVENT, { detail: { name } }))
  }
  return false
}
