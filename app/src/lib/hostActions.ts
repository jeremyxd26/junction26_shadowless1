// Hands an action over to the host app in the `sentti.<name>` envelope (docs/integration.md
// section 3). Inside a host the message goes through `sendToHost`; in a plain browser nothing is
// sent and `HostNotice` tells the customer that this step continues in the bank app.
import type { Num } from '../api/types.ts'
import { hostPlatform, sendToHost, type HostScope } from './hostBridge.ts'

/** The action's `draft` of `add_to_payments` (contract §11.3), passed to the host unchanged. */
export type PaymentDraft = {
  /** `null` for a barcode without a payee; the host then asks for it. */
  payee: string | null
  iban: string
  reference: string
  /** A Number object (contract §2.1), so the host shows the same `display` the customer saw. */
  amount: Num
  due_date: string
}

/** The host's own screens of the action `open_host_screen` (contract 0.3.1, PR #308). */
export type HostScreenTarget = 'monthly_saving' | 'bonus_to_fund'

/** Every message the module hands over, by name (camelCase), with its payload. */
export type HandOverPayloads = {
  close: Record<string, never>
  paymentDraft: PaymentDraft
  openHostScreen: { target: HostScreenTarget }
}

export type HandOverName = keyof HandOverPayloads

const HOST_SCREEN_TARGETS: readonly HostScreenTarget[] = ['monthly_saving', 'bonus_to_fund']

/** The action's `target` when the app knows it, else null: an unknown target renders nothing. */
export function hostScreenTarget(target: unknown): HostScreenTarget | null {
  return HOST_SCREEN_TARGETS.find((known) => known === target) ?? null
}

export interface HandOverOptions {
  /** Do not show the notice when no host takes the message (e.g. the demo's own mock sheets). */
  silent?: boolean
  /** The host globals; `window` by default, a stub in tests. */
  scope?: HostScope
}

/** The window event `HostNotice` listens to; fired when no host listens. */
export const HANDOVER_EVENT = 'sentti:handover'

export interface HandOverDetail {
  name: HandOverName
}

/**
 * Sends `sentti.<name>` with `payload`, unchanged, to the host. Returns true when the host took it.
 * Without a host (a plain browser) it returns false and fires `HANDOVER_EVENT`, unless `silent`, so
 * the notice can show. When a host exists but its handler throws, it returns false and fires
 * nothing: "This continues in the bank app" would not be true then.
 */
export function handOver<N extends HandOverName>(
  name: N,
  payload: HandOverPayloads[N],
  { silent = false, scope }: HandOverOptions = {},
): boolean {
  if (sendToHost(name, payload as Record<string, unknown>, scope)) return true
  if (!silent && hostPlatform(scope) === null && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<HandOverDetail>(HANDOVER_EVENT, { detail: { name } }))
  }
  return false
}

/** The action `open_host_screen`: sends `sentti.openHostScreen` with `{target}` and nothing else. */
export function openHostScreen(target: HostScreenTarget, options?: HandOverOptions): boolean {
  return handOver('openHostScreen', { target }, options)
}
