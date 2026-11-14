import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HANDOVER_EVENT, handOver, type HandOverDetail, type PaymentDraft } from './hostActions.ts'
import type { HostScope } from './hostBridge.ts'

// The payload of the contract's example `host.payment_draft` (contracts/api.md section 11.3).
const DRAFT: PaymentDraft = {
  payee: 'Esimerkki Asunnot Oy',
  iban: 'FI2112345600000785',
  reference: '1232',
  amount: {
    value: 812.4,
    unit: 'eur',
    period: { start: '2026-10-01', end: '2026-10-01', label: '1 Oct 2026' },
    method: 'bill_barcode@1',
    evidence_ref: null,
    label: 'Amount due',
    display: '€812.40',
  },
  due_date: '2026-10-01',
}
const DRAFT_MESSAGE = { type: 'sentti.paymentDraft', v: 1, payload: DRAFT }
const SCREEN_MESSAGE = { type: 'sentti.openHostScreen', v: 1, payload: { target: 'monthly_saving' } }

function iosScope() {
  const postMessage = vi.fn()
  return { scope: { webkit: { messageHandlers: { sentti: { postMessage } } } } as HostScope, postMessage }
}

function androidScope() {
  const postMessage = vi.fn()
  return { scope: { sentti: { postMessage } } as HostScope, postMessage }
}

describe('handOver', () => {
  const names: string[] = []
  const onEvent = (event: Event) => names.push((event as CustomEvent<HandOverDetail>).detail.name)
  // The tests run in Node: a bare EventTarget stands in for `window`.
  beforeEach(() => {
    names.length = 0
    vi.stubGlobal('window', new EventTarget())
    window.addEventListener(HANDOVER_EVENT, onEvent)
  })
  afterEach(() => {
    window.removeEventListener(HANDOVER_EVENT, onEvent)
    vi.unstubAllGlobals()
  })

  it('posts the payment draft as an object on iOS, payload unchanged, and fires no notice', () => {
    const { scope, postMessage } = iosScope()
    expect(handOver('paymentDraft', DRAFT, { scope })).toBe(true)
    expect(postMessage).toHaveBeenCalledWith(DRAFT_MESSAGE)
    expect(postMessage.mock.calls[0][0].payload).toBe(DRAFT)
    expect(names).toEqual([])
  })

  it('posts the payment draft as a JSON string on Android, payload unchanged, and fires no notice', () => {
    const { scope, postMessage } = androidScope()
    expect(handOver('paymentDraft', DRAFT, { scope })).toBe(true)
    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(typeof postMessage.mock.calls[0][0]).toBe('string')
    expect(JSON.parse(postMessage.mock.calls[0][0] as string)).toEqual(DRAFT_MESSAGE)
    expect(names).toEqual([])
  })

  it('sends openHostScreen with only the target', () => {
    const { scope, postMessage } = iosScope()
    expect(handOver('openHostScreen', { target: 'monthly_saving' }, { scope })).toBe(true)
    expect(postMessage).toHaveBeenCalledWith(SCREEN_MESSAGE)
  })

  it('returns false without a host and fires the notice event with the message name', () => {
    expect(handOver('openHostScreen', { target: 'monthly_saving' }, { scope: {} })).toBe(false)
    expect(names).toEqual(['openHostScreen'])
  })

  it('returns false without a host and fires nothing when silent', () => {
    expect(handOver('paymentDraft', DRAFT, { scope: {}, silent: true })).toBe(false)
    expect(names).toEqual([])
  })

  it('returns false and fires no notice when the host handler throws', () => {
    const postMessage = vi.fn(() => {
      throw new Error('host failed')
    })
    expect(handOver('paymentDraft', DRAFT, { scope: { sentti: { postMessage } } as HostScope })).toBe(false)
    expect(names).toEqual([])
  })

  it('does not compile with a wrong payload', () => {
    const scope: HostScope = {}
    // @ts-expect-error a target outside the contract's list
    handOver('openHostScreen', { target: 'savings' }, { scope, silent: true })
    // @ts-expect-error the amount must be a Number object, not a string
    handOver('paymentDraft', { ...DRAFT, amount: '812.40' }, { scope, silent: true })
    // @ts-expect-error a payment draft without its due date
    handOver('paymentDraft', { payee: null, iban: DRAFT.iban, reference: DRAFT.reference, amount: DRAFT.amount }, { scope, silent: true })
    // @ts-expect-error close carries an empty payload
    handOver('close', { reason: 'done' }, { scope, silent: true })
    // @ts-expect-error a message name the module does not hand over
    handOver('handoff', {}, { scope, silent: true })
    expect(names).toEqual([])
  })
})
