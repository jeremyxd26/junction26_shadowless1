import { describe, expect, it, vi } from 'vitest'
import type { BillExplainResponse } from '../api/billTypes.ts'
import contract from '../api/mock/contract-examples.json'
import { addToPayments, paymentAction } from './addToPayments.ts'
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

  it('returns false outside a host, so the notice can show', () => {
    expect(addToPayments(paymentAction(response.actions)!, {} as HostScope)).toBe(false)
  })

  it('finds no action when a check failed', () => {
    expect(paymentAction(unknown.actions)).toBeNull()
  })
})
