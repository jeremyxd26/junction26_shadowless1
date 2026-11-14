import { describe, expect, it } from 'vitest'
import type { BillExplainRequest, BillReadResponse } from '../api/billTypes.ts'
import contract from '../api/mock/contract-examples.json'
import { buildExplainRequest, initialInputs, normaliseAmount, type FieldInputs } from './billRequest.ts'

const examples = contract.examples as unknown as Record<string, unknown>
const reading = examples['bill.read_response'] as BillReadResponse
const barcodeRequest = examples['bill.request'] as BillExplainRequest
const fieldsRequest = examples['bill.request_fields'] as BillExplainRequest

const base = { customerId: 'CUST00042', language: 'en' as const }

describe('buildExplainRequest', () => {
  it('sends the confirmed barcode with the payee beside it when nothing else was edited', () => {
    const result = buildExplainRequest({ ...base, reading, inputs: initialInputs(reading) })
    expect(result).toEqual({ ok: true, request: barcodeRequest })
  })

  it('keeps the barcode when only the payee was corrected, and sends an empty payee as null', () => {
    const renamed = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), payee: ' Esimerkki Koti Oy ' } })
    expect(renamed).toEqual({ ok: true, request: { ...barcodeRequest, payee: 'Esimerkki Koti Oy' } })
    const empty = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), payee: '' } })
    expect(empty).toEqual({ ok: true, request: { ...barcodeRequest, payee: null } })
  })

  it('switches to the five fields when the amount was edited, with the comma made a dot', () => {
    const inputs = { ...initialInputs(reading), amount: '812,04' }
    const result = buildExplainRequest({ ...base, reading, inputs })
    expect(result).toEqual({
      ok: true,
      request: {
        customer_id: 'CUST00042',
        language: 'en',
        barcode: null,
        payee: null,
        fields: { payee: 'Esimerkki Asunnot Oy', iban: 'FI2112345600000785', reference: '1232', amount: '812.04', due_date: '2026-10-01' },
      },
    })
  })

  it('builds the contract fields request from typed fields (the typed fallback)', () => {
    const inputs: FieldInputs = { ...fieldsRequest.fields! }
    expect(initialInputs(null)).toEqual({ payee: '', iban: '', reference: '', amount: '', due_date: '' })
    expect(buildExplainRequest({ ...base, reading: null, inputs })).toEqual({ ok: true, request: fieldsRequest })
  })

  it('never sends payee beside fields, nor the read objects', () => {
    const result = buildExplainRequest({ ...base, reading, inputs: { ...initialInputs(reading), reference: '1245' } })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.request.payee).toBeNull()
    expect(result.request.barcode).toBeNull()
    expect(Object.values(result.request.fields!).every((value) => typeof value === 'string')).toBe(true)
  })

  it('reports empty and over-long fields instead of sending them', () => {
    const inputs: FieldInputs = { payee: '', iban: 'F'.repeat(43), reference: '', amount: '', due_date: '' }
    expect(buildExplainRequest({ ...base, reading: null, inputs })).toEqual({
      ok: false,
      missingCustomer: false,
      problems: { payee: 'required', iban: 'too_long', reference: 'required', amount: 'required', due_date: 'required' },
    })
  })

  it('sends nothing without a customer', () => {
    const result = buildExplainRequest({ ...base, customerId: null, reading, inputs: initialInputs(reading) })
    expect(result).toEqual({ ok: false, problems: {}, missingCustomer: true })
  })

  it('does not use a barcode longer than 80 characters', () => {
    const long = structuredClone(reading)
    long.fields.barcode!.value = '4'.repeat(81)
    const result = buildExplainRequest({ ...base, reading: long, inputs: initialInputs(long) })
    expect(result.ok && result.request.barcode).toBe(null)
  })
})

describe('normaliseAmount', () => {
  it.each([
    ['145', '145'],
    ['145,5', '145.5'],
    [' 812,40 ', '812.40'],
    ['100000', '100000'],
    ['100000.00', '100000.00'],
    ['0.01', '0.01'],
  ])('accepts %j as %j', (typed, amount) => {
    expect(normaliseAmount(typed)).toEqual({ amount })
  })

  it.each([
    ['', 'required'],
    ['12.345', 'amount_format'],
    ['1 000', 'amount_format'],
    ['€12', 'amount_format'],
    ['-5', 'amount_format'],
    ['0,00', 'amount_range'],
    ['100000.01', 'amount_range'],
    ['200000', 'amount_range'],
  ])('refuses %j (%s)', (typed, problem) => {
    expect(normaliseAmount(typed)).toEqual({ problem })
  })
})
