import { describe, expect, it, vi } from 'vitest'
import type { BillExplainResponse } from '../api/billTypes.ts'
import contract from '../api/mock/contract-examples.json'
import { addToPayments, hostScreenActions, paymentAction } from './addToPayments.ts'
import type { HostScreenTarget } from './hostActions.ts'
import type { HostScope } from './hostBridge.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const response = examples['bill.response'] as BillExplainResponse
const unknown = examples['bill.response_unknown'] as BillExplainResponse

describe('addToPayments', () => {
  it('sends the contract host message, with the draft exactly as the action carries it (iOS)', () => {
    const postMessage = vi.fn()
    const scope = { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope
    const action = paymentAction(response.actions)!
    expect(addToPayments(action, scope)).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    const [message] = postMessage.mock.calls[0]
    expect(message).toEqual(examples['host.payment_draft'])
    expect(message.payload).toEqual(action.draft)
    expect(message.payload.amount).toEqual(action.draft.amount)
  })

  it('sends the same envelope as a JSON string on Android', () => {
    const postMessage = vi.fn()
    const scope = { sentti: { postMessage } } as HostScope
    expect(addToPayments(paymentAction(response.actions)!, scope)).toBe(true)
    expect(JSON.parse(postMessage.mock.calls[0][0])).toEqual(examples['host.payment_draft'])
  })

  it('sends only the five contract fields when the draft carries more', () => {
    const postMessage = vi.fn()
    const scope = { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope
    const action = paymentAction(response.actions)!
    const extended = { ...action, draft: { ...action.draft, account_holder: 'Someone', internal_id: 'x1' } }
    expect(addToPayments(extended, scope)).toBe(true)
    const [message] = postMessage.mock.calls[0]
    expect(Object.keys(message.payload).sort()).toEqual(['amount', 'due_date', 'iban', 'payee', 'reference'])
    expect(message.payload).not.toHaveProperty('account_holder')
    expect(message).toEqual(examples['host.payment_draft'])
  })

  it('returns false outside a host, so the notice can show', () => {
    expect(addToPayments(paymentAction(response.actions)!, {} as HostScope)).toBe(false)
  })

  it('finds no action when a check failed', () => {
    expect(paymentAction(unknown.actions)).toBeNull()
  })

  it('keeps the payment action whatever the forecast says', () => {
    for (const status of ['covered', 'tight', 'not_covered', 'outside_forecast']) {
      const withForecast = { ...response, forecast: { ...(response.forecast ?? {}), status } }
      expect(paymentAction(withForecast.actions)).toEqual(response.actions[0])
    }
  })

})

describe('the bill actions (contract 0.3.3)', () => {
  const contactBank = { type: 'open_host_screen', label: 'Contact S-Pankki', target: 'contact_bank' }
  // #470 adds contact_bank to the app's known targets; until then it is injected here.
  const knowsContactBank = (target: unknown) =>
    (['monthly_saving', 'bonus_to_fund', 'contact_bank'] as unknown[]).includes(target) ? (target as HostScreenTarget) : null

  it('shows both Add to payments and the contact chip when a sign brings contact_bank', () => {
    const actions = [...response.actions, contactBank]
    expect(paymentAction(actions)).toEqual(response.actions[0])
    expect(hostScreenActions(actions, knowsContactBank)).toEqual([{ label: 'Contact S-Pankki', target: 'contact_bank' }])
  })

  it('shows only Add to payments without signs that bring contact_bank', () => {
    expect(paymentAction(response.actions)).not.toBeNull()
    expect(hostScreenActions(response.actions, knowsContactBank)).toEqual([])
  })

  it('shows only the contact chip after a failed check, picking actions by type, not index', () => {
    const actions = [contactBank]
    expect(paymentAction(actions)).toBeNull()
    expect(hostScreenActions(actions, knowsContactBank)).toHaveLength(1)
  })

  it('renders nothing for a target the app does not know', () => {
    const unknownTarget = { type: 'open_host_screen', label: 'Somewhere', target: 'not_a_screen' }
    expect(hostScreenActions([unknownTarget])).toEqual([])
    expect(hostScreenActions([{ type: 'open_host_screen', label: 'Save monthly', target: 'monthly_saving' }])).toEqual([
      { label: 'Save monthly', target: 'monthly_saving' },
    ])
  })
})
